#!/usr/bin/env python3
"""
SD1.5 IC-Light relighting runner for RTX 3080 Ti.

The default path uses the official background-conditioned FBC checkpoint:
foreground + background are VAE-encoded as concat conditions, and transparent
foreground pixels are neutral grey before encoding. The older FC path remains
available only as a diagnostic.

Usage:
    python3 scripts/run_ic_flux.py --plate ... --cg ... --alpha ... --out-dir ...

Requires:
    - iclight weights (weights/ic-light-v2/)
    - SD1.5 base model: stablediffusionapi/realistic-vision-v51 (or runwayml/stable-diffusion-v1-5)
"""
import os, sys, math, json
from pathlib import Path
import numpy as np
import torch
import safetensors.torch as sf
from PIL import Image, ImageFilter
from diffusers import StableDiffusionPipeline, StableDiffusionImg2ImgPipeline
from diffusers import AutoencoderKL, UNet2DConditionModel, DDIMScheduler, EulerAncestralDiscreteScheduler, DPMSolverMultistepScheduler
from diffusers.models.attention_processor import AttnProcessor2_0
from transformers import CLIPTextModel, CLIPTokenizer

# ── Config ────────────────────────────────────────────────────────────────────
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
SD15_NAME = 'stablediffusionapi/realistic-vision-v51'  # base SD15 model
IC_LIGHT_DIR = Path(__file__).parent.parent / 'weights' / 'ic-light-v2'
OUTPUT_DIR = Path('runs/overnight_harmonic_sweep/ic_flux')
IC_LIGHT_MODELS = {
    'fc': {
        'file': 'iclight_sd15_fc.safetensors',
        'conv_in_channels': 8,
        'description': 'foreground/text conditioned diagnostic model',
    },
    'fbc': {
        'file': 'iclight_sd15_fbc.safetensors',
        'conv_in_channels': 12,
        'description': 'foreground + background conditioned model',
    },
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_rgb(path):
    return np.array(Image.open(path).convert("RGB")).astype(np.float32) / 255.0

def load_rgba(path):
    a = np.array(Image.open(path).convert("RGBA"))
    return a[:, :, :3].astype(np.float32) / 255.0, a[:, :, 3].astype(np.float32) / 255.0

def save_rgb(path, arr):
    Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8)).save(path)

def to_uint8_rgb(arr):
    return (np.clip(arr, 0, 1) * 255).astype(np.uint8)

def composite(fg, bg, a):
    a3 = a[..., None] if a.ndim == 2 else a
    return fg * a3 + bg * (1 - a3)

def prepare_foreground_condition(cg_rgb, alpha_2d):
    """Match IC-Light practice: neutral grey outside the foreground matte."""
    a3 = alpha_2d[..., None] if alpha_2d.ndim == 2 else alpha_2d
    fg_255 = cg_rgb * 255.0
    return (127.0 + (fg_255 - 127.0) * a3).clip(0, 255).astype(np.uint8)

def luma(rgb):
    return rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)

def gaussian_blur01(arr, radius):
    if radius <= 0:
        return arr.astype(np.float32)
    pil = Image.fromarray(to_uint8_rgb(arr))
    return np.asarray(pil.filter(ImageFilter.GaussianBlur(radius=float(radius))),
                      dtype=np.float32) / 255.0

def masked_gaussian_blur(rgb, alpha_2d, radius):
    a3 = alpha_2d[..., None] if alpha_2d.ndim == 2 else alpha_2d
    num = gaussian_blur01(rgb * a3, radius)
    den = gaussian_blur01(np.repeat(a3, 3, axis=2), radius)
    return num / np.maximum(den, 1e-4)

def lowfreq_lighting_transfer(cg_rgb, generated_rgb, alpha_2d, strength=1.0,
                              color_strength=0.35, blur_radius=12.0,
                              ratio_min=0.55, ratio_max=1.0):
    """Use IC-Light for broad illumination while preserving original CG detail."""
    cg_low = masked_gaussian_blur(cg_rgb, alpha_2d, blur_radius)
    gen_low = masked_gaussian_blur(generated_rgb, alpha_2d, blur_radius)

    lum_ratio = np.clip(
        luma(gen_low) / (luma(cg_low) + 1e-4),
        ratio_min,
        ratio_max,
    )[..., None]
    out = cg_rgb * (1.0 + strength * (lum_ratio - 1.0))

    color_ratio = np.clip(gen_low / (cg_low + 1e-4), 0.75, 1.25)
    out = out * (1.0 + color_strength * (color_ratio - 1.0))
    return np.clip(out, 0, 1)

def resize_without_crop(image, target_width, target_height):
    pil = Image.fromarray(image)
    return np.array(pil.resize((target_width, target_height), Image.LANCZOS))

def resize_and_center_crop(image, target_width, target_height):
    pil = Image.fromarray(image)
    w, h = pil.size
    scale = max(target_width / w, target_height / h)
    rw, rh = int(round(w * scale)), int(round(h * scale))
    resized = pil.resize((rw, rh), Image.LANCZOS)
    left = (rw - target_width) / 2
    top = (rh - target_height) / 2
    cropped = resized.crop((left, top, left + target_width, top + target_height))
    return np.array(cropped)


@torch.inference_mode()
def numpy2pytorch(imgs):
    h = torch.from_numpy(np.stack(imgs, axis=0)).float() / 127.0 - 1.0
    h = h.movedim(-1, 1)
    return h


@torch.inference_mode()
def pytorch2numpy(imgs, quant=True):
    results = []
    for x in imgs:
        y = x.movedim(0, -1)
        if quant:
            y = y * 127.5 + 127.5
            y = y.detach().float().cpu().numpy().clip(0, 255).astype(np.uint8)
        else:
            y = y * 0.5 + 0.5
            y = y.detach().float().cpu().numpy().clip(0, 1).astype(np.float32)
        results.append(y)
    return results


@torch.inference_mode()
def encode_prompt_inner(txt, tokenizer, text_encoder, device):
    # Handle empty string
    if not txt or not txt.strip():
        txt = "normal"
    max_length = tokenizer.model_max_length
    chunk_length = tokenizer.model_max_length - 2
    id_start = tokenizer.bos_token_id
    id_end = tokenizer.eos_token_id
    id_pad = id_end

    def pad(x, p, i):
        return x[:i] if len(x) >= i else x + [p] * (i - len(x))

    tokens = tokenizer(txt, truncation=False, add_special_tokens=False)["input_ids"]
    # Edge case: empty or all-special tokens
    if not tokens:
        tokens = [tokenizer.eos_token_id]
    chunks = [[id_start] + tokens[i:i+chunk_length] + [id_end] for i in range(0, len(tokens), chunk_length)]
    chunks = [pad(ck, id_pad, max_length) for ck in chunks]
    token_ids = torch.tensor(chunks).to(device=device, dtype=torch.int64)
    conds = text_encoder(token_ids).last_hidden_state
    return conds


@torch.inference_mode()
def encode_prompt_pair(positive_prompt, negative_prompt, tokenizer, text_encoder, device):
    c = encode_prompt_inner(positive_prompt, tokenizer, text_encoder, device)
    uc = encode_prompt_inner(negative_prompt, tokenizer, text_encoder, device)
    c_len = float(len(c)); uc_len = float(len(uc))
    max_count = max(c_len, uc_len)
    c_repeat = int(math.ceil(max_count / c_len))
    uc_repeat = int(math.ceil(max_count / uc_len))
    max_chunk = max(len(c), len(uc))
    c = torch.cat([c] * c_repeat, dim=0)[:max_chunk]
    uc = torch.cat([uc] * uc_repeat, dim=0)[:max_chunk]
    c = torch.cat([p[None, ...] for p in c], dim=1)
    uc = torch.cat([p[None, ...] for p in uc], dim=1)
    return c, uc


# ── Pipeline setup ────────────────────────────────────────────────────────────

def setup_pipeline(ic_model='fbc'):
    if ic_model not in IC_LIGHT_MODELS:
        raise ValueError(f"Unsupported IC-Light model '{ic_model}'")
    model_cfg = IC_LIGHT_MODELS[ic_model]

    print(f"Setting up IC-Light pipeline on {DEVICE}")
    print(f"Loading SD15 base model: {SD15_NAME} (will auto-download if not cached)")
    print(f"Using IC-Light {ic_model}: {model_cfg['description']}")

    # Load tokenizer + text encoder
    tokenizer = CLIPTokenizer.from_pretrained(SD15_NAME, subfolder="tokenizer")
    text_encoder = CLIPTextModel.from_pretrained(SD15_NAME, subfolder="text_encoder")

    # Load VAE
    vae = AutoencoderKL.from_pretrained(SD15_NAME, subfolder="vae")

    # Load UNet
    unet = UNet2DConditionModel.from_pretrained(SD15_NAME, subfolder="unet")

    # Patch UNet conv_in to accept the original latent plus IC-Light concat
    # condition latents: FC = 4+4, FBC = 4+4+4.
    with torch.no_grad():
        new_conv_in = torch.nn.Conv2d(
            model_cfg['conv_in_channels'], unet.conv_in.out_channels,
            unet.conv_in.kernel_size, unet.conv_in.stride, unet.conv_in.padding
        )
        new_conv_in.weight.zero_()
        new_conv_in.weight[:, :4, :, :].copy_(unet.conv_in.weight)
        new_conv_in.bias = unet.conv_in.bias
        unet.conv_in = new_conv_in

    # Save original forward and hook
    unet_original_forward = unet.forward

    def hooked_unet_forward(sample, timestep, encoder_hidden_states, **kwargs):
        c_concat = kwargs['cross_attention_kwargs']['concat_conds'].to(sample)
        c_concat = torch.cat([c_concat] * (sample.shape[0] // c_concat.shape[0]), dim=0)
        new_sample = torch.cat([sample, c_concat], dim=1)
        kwargs['cross_attention_kwargs'] = {}
        return unet_original_forward(new_sample, timestep, encoder_hidden_states, **kwargs)

    unet.forward = hooked_unet_forward

    # Load IC-Light weights and apply as offset to UNet
    model_path = IC_LIGHT_DIR / model_cfg['file']
    print(f"Loading IC-Light weights from {model_path}")
    sd_offset = sf.load_file(str(model_path))
    sd_origin = unet.state_dict()
    keys = sd_origin.keys()
    sd_merged = {k: sd_origin[k] + sd_offset[k] for k in sd_origin.keys()}
    unet.load_state_dict(sd_merged, strict=True)
    del sd_offset, sd_origin, sd_merged, keys
    print("IC-Light weights applied to UNet.")

    # Move to GPU
    text_encoder = text_encoder.to(device=DEVICE, dtype=torch.float16)
    vae = vae.to(device=DEVICE, dtype=torch.bfloat16)
    unet = unet.to(device=DEVICE, dtype=torch.float16)

    # Set attention processors
    unet.set_attn_processor(AttnProcessor2_0())
    vae.set_attn_processor(AttnProcessor2_0())

    # Scheduler
    ddim_scheduler = DDIMScheduler(
        num_train_timesteps=1000, beta_start=0.00085, beta_end=0.012,
        beta_schedule="scaled_linear", clip_sample=False,
        set_alpha_to_one=False, steps_offset=1,
    )
    euler_a_scheduler = EulerAncestralDiscreteScheduler(
        num_train_timesteps=1000, beta_start=0.00085, beta_end=0.012, steps_offset=1
    )
    dpmpp_2m_sde_karras_scheduler = DPMSolverMultistepScheduler(
        num_train_timesteps=1000, beta_start=0.00085, beta_end=0.012,
        algorithm_type="sde-dpmsolver++", use_karras_sigmas=True, steps_offset=1
    )

    # Create pipelines
    t2i_pipe = StableDiffusionPipeline(
        vae=vae, text_encoder=text_encoder, tokenizer=tokenizer, unet=unet,
        scheduler=dpmpp_2m_sde_karras_scheduler, safety_checker=None,
        requires_safety_checker=False, feature_extractor=None, image_encoder=None
    )
    i2i_pipe = StableDiffusionImg2ImgPipeline(
        vae=vae, text_encoder=text_encoder, tokenizer=tokenizer, unet=unet,
        scheduler=dpmpp_2m_sde_karras_scheduler, safety_checker=None,
        requires_safety_checker=False, feature_extractor=None, image_encoder=None
    )

    return {
        'tokenizer': tokenizer,
        'text_encoder': text_encoder,
        'vae': vae,
        'unet': unet,
        't2i_pipe': t2i_pipe,
        'i2i_pipe': i2i_pipe,
        'device': DEVICE,
        'ic_model': ic_model,
    }


@torch.inference_mode()
def encode_concat_conds(pipeline, fg_uint8, bg_uint8, image_width, image_height):
    vae = pipeline['vae']
    fg = resize_and_center_crop(fg_uint8, image_width, image_height)
    imgs = [fg]
    if pipeline['ic_model'] == 'fbc':
        bg = resize_and_center_crop(bg_uint8, image_width, image_height)
        imgs.append(bg)

    concat_conds = numpy2pytorch(imgs).to(device=vae.device, dtype=vae.dtype)
    concat_conds = vae.encode(concat_conds).latent_dist.mode() * vae.config.scaling_factor
    return torch.cat([c[None, ...] for c in concat_conds], dim=1)


@torch.inference_mode()
def run_ic_light_relight(pipeline, fg_uint8, bg_uint8, prompt, seed=42, steps=20, cfg=7.0,
                          image_width=768, image_height=432,
                          num_samples=1, a_prompt='best quality',
                          n_prompt='lowres, bad anatomy, bad hands, cropped, worst quality',
                          highres_scale=1.5, highres_denoise=0.5):
    """
    Run IC-Light relighting with official-style concat conditioning.
    fg_uint8: grey-matted foreground RGB in [0,255]
    bg_uint8: background/plate RGB in [0,255]
    Returns: list of relit HxWx3 numpy arrays in [0,1]
    """
    text_encoder = pipeline['text_encoder']
    vae = pipeline['vae']
    t2i_pipe = pipeline['t2i_pipe']
    i2i_pipe = pipeline['i2i_pipe']
    device = pipeline['device']
    tokenizer = pipeline['tokenizer']

    # Encode prompt
    conds, unconds = encode_prompt_pair(
        positive_prompt=prompt + ', ' + a_prompt,
        negative_prompt=n_prompt or 'overexposed, washed out, low contrast',
        tokenizer=tokenizer, text_encoder=text_encoder, device=device
    )

    concat_conds = encode_concat_conds(pipeline, fg_uint8, bg_uint8, image_width, image_height)

    rng = torch.Generator(device=device).manual_seed(int(seed))

    # Text-to-latent with IC-Light concat conditioning.
    latents = t2i_pipe(
        prompt_embeds=conds,
        negative_prompt_embeds=unconds,
        width=image_width,
        height=image_height,
        num_inference_steps=steps,
        num_images_per_prompt=num_samples,
        generator=rng,
        output_type='latent',
        guidance_scale=cfg,
        cross_attention_kwargs={'concat_conds': concat_conds},
    ).images.to(vae.dtype) / vae.config.scaling_factor

    if highres_scale > 1.0 and highres_denoise > 0.0:
        pixels = vae.decode(latents).sample
        pixels = pytorch2numpy(pixels)
        pixels = [
            resize_without_crop(
                p,
                target_width=int(round(image_width * highres_scale / 64.0) * 64),
                target_height=int(round(image_height * highres_scale / 64.0) * 64),
            )
            for p in pixels
        ]

        pixels = numpy2pytorch(pixels).to(device=vae.device, dtype=vae.dtype)
        latents = vae.encode(pixels).latent_dist.mode() * vae.config.scaling_factor
        latents = latents.to(device=pipeline['unet'].device, dtype=pipeline['unet'].dtype)

        image_height, image_width = latents.shape[2] * 8, latents.shape[3] * 8
        concat_conds = encode_concat_conds(pipeline, fg_uint8, bg_uint8, image_width, image_height)

        latents = i2i_pipe(
            image=latents,
            strength=highres_denoise,
            prompt_embeds=conds,
            negative_prompt_embeds=unconds,
            width=image_width,
            height=image_height,
            num_inference_steps=max(1, int(round(steps / highres_denoise))),
            num_images_per_prompt=num_samples,
            generator=rng,
            output_type='latent',
            guidance_scale=cfg,
            cross_attention_kwargs={'concat_conds': concat_conds},
        ).images.to(vae.dtype) / vae.config.scaling_factor

    pixels = vae.decode(latents).sample
    pixels = pytorch2numpy(pixels, quant=False)

    return pixels


def relight_with_composite(pipeline, plate_rgb, cg_rgb, alpha_2d, prompt,
                            seed=42, steps=20, cfg=7.0,
                            image_width=768, image_height=432,
                            a_prompt='best quality',
                            n_prompt='lowres, bad anatomy, bad hands, cropped, worst quality',
                            highres_scale=1.5, highres_denoise=0.5,
                            transfer_mode='lowfreq', transfer_strength=1.0,
                            transfer_color_strength=0.35,
                            transfer_blur_radius=12.0,
                            transfer_ratio_min=0.55,
                            transfer_ratio_max=1.0):
    """
    Run IC-Light on grey-matted CG + plate conditioning, then composite over plate.
    Returns adjusted foreground (HxWx3) and final composite (HxWx3).
    """
    fg_condition = prepare_foreground_condition(cg_rgb, alpha_2d)
    bg_condition = to_uint8_rgb(plate_rgb)

    relit = run_ic_light_relight(
        pipeline, fg_condition, bg_condition, prompt,
        seed=seed, steps=steps, cfg=cfg,
        image_width=image_width, image_height=image_height,
        a_prompt=a_prompt, n_prompt=n_prompt,
        highres_scale=highres_scale, highres_denoise=highres_denoise,
    )
    relit_rgb = relit[0]  # HxWx3 in [0,1], at inference resolution

    # IC-Light runs at a reduced inference resolution; resize the relit
    # foreground back to the plate/alpha resolution before compositing so the
    # A-over-B contract holds at native size.
    plate_h, plate_w = plate_rgb.shape[:2]
    if relit_rgb.shape[:2] != (plate_h, plate_w):
        relit_rgb = resize_without_crop(
            (np.clip(relit_rgb, 0, 1) * 255).astype(np.uint8), plate_w, plate_h
        ).astype(np.float32) / 255.0

    model_rgb = relit_rgb.copy()
    if transfer_mode == 'lowfreq':
        relit_rgb = lowfreq_lighting_transfer(
            cg_rgb, model_rgb, alpha_2d,
            strength=transfer_strength,
            color_strength=transfer_color_strength,
            blur_radius=transfer_blur_radius,
            ratio_min=transfer_ratio_min,
            ratio_max=transfer_ratio_max,
        )
    elif transfer_mode != 'none':
        raise ValueError(f"Unsupported transfer mode '{transfer_mode}'")

    # Composite relit foreground over plate using alpha
    final = composite(relit_rgb, plate_rgb, alpha_2d)

    return relit_rgb, final, model_rgb


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description='IC-Light relighting runner')
    parser.add_argument('--plate', required=True, help='Plate background PNG')
    parser.add_argument('--cg', required=True, help='CG foreground RGBA PNG')
    parser.add_argument('--alpha', required=True, help='Alpha mask PNG')
    parser.add_argument('--out-dir', default=str(OUTPUT_DIR), help='Output directory')
    parser.add_argument('--ic-model', choices=sorted(IC_LIGHT_MODELS), default='fbc',
                        help='IC-Light checkpoint family. fbc is the official foreground+background path.')
    parser.add_argument('--prompt', default='harmonize lighting, match plate illumination',
                        help='Relighting prompt')
    parser.add_argument('--a-prompt', default='best quality',
                        help='Added positive prompt, matching the official demo default.')
    parser.add_argument('--n-prompt', default='lowres, bad anatomy, bad hands, cropped, worst quality',
                        help='Negative prompt, matching the official demo default.')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--steps', type=int, default=20)
    parser.add_argument('--cfg', type=float, default=7.0)
    parser.add_argument('--width', type=int, default=768)
    parser.add_argument('--height', type=int, default=432)
    parser.add_argument('--highres-scale', type=float, default=1.5)
    parser.add_argument('--highres-denoise', type=float, default=0.5)
    parser.add_argument('--transfer-mode', choices=['lowfreq', 'none'], default='lowfreq',
                        help='Postprocess generated IC-Light output back onto original CG detail.')
    parser.add_argument('--transfer-strength', type=float, default=1.0)
    parser.add_argument('--transfer-color-strength', type=float, default=0.35)
    parser.add_argument('--transfer-blur-radius', type=float, default=12.0)
    parser.add_argument('--transfer-ratio-min', type=float, default=0.55)
    parser.add_argument('--transfer-ratio-max', type=float, default=1.0)
    args = parser.parse_args()

    import time, resource, hashlib
    from datetime import datetime, timezone

    def _sha256(path):
        h = hashlib.sha256()
        with open(path, 'rb') as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b''):
                h.update(chunk)
        return h.hexdigest()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading inputs...")
    plate_rgb = load_rgb(args.plate)
    cg_rgb, cg_alpha = load_rgba(args.cg)
    ext_alpha = load_rgb(args.alpha)
    # ext_alpha may be HxW (grayscale) or HxWx3; reduce to a single channel
    if ext_alpha.ndim == 3:
        ext_alpha = ext_alpha[..., 0]
    combined = np.minimum(ext_alpha, cg_alpha)

    print(f"  plate: {plate_rgb.shape}, cg: {cg_rgb.shape}, alpha: {combined.shape}")
    print(f"  prompt: {args.prompt}")
    print(f"  ic_model: {args.ic_model}")

    fg_condition = prepare_foreground_condition(cg_rgb, combined)
    Image.fromarray(fg_condition).save(out_dir / 'ic_light_fg_condition.png')
    save_rgb(out_dir / 'ic_light_bg_condition.png', plate_rgb)

    print("\nSetting up pipeline (downloading SD15 base if needed)...")
    t_load0 = time.perf_counter()
    pipeline = setup_pipeline(ic_model=args.ic_model)
    t_load = time.perf_counter() - t_load0

    print(
        f"\nRunning IC-Light relighting "
        f"(seed={args.seed}, steps={args.steps}, cfg={args.cfg}, "
        f"highres={args.highres_scale}/{args.highres_denoise})..."
    )
    t_inf0 = time.perf_counter()
    relit_fg, final_comp, model_fg = relight_with_composite(
        pipeline, plate_rgb, cg_rgb, combined,
        prompt=args.prompt,
        seed=args.seed, steps=args.steps, cfg=args.cfg,
        image_width=args.width, image_height=args.height,
        a_prompt=args.a_prompt, n_prompt=args.n_prompt,
        highres_scale=args.highres_scale, highres_denoise=args.highres_denoise,
        transfer_mode=args.transfer_mode,
        transfer_strength=args.transfer_strength,
        transfer_color_strength=args.transfer_color_strength,
        transfer_blur_radius=args.transfer_blur_radius,
        transfer_ratio_min=args.transfer_ratio_min,
        transfer_ratio_max=args.transfer_ratio_max,
    )
    t_inf = time.perf_counter() - t_inf0

    # Raw A-over-B (un-relit) — the seam-check baseline for the Phase 2 gate.
    raw_over = composite(cg_rgb, plate_rgb, combined)
    delta = np.abs(relit_fg - cg_rgb)
    alpha_weighted_delta = delta * (combined[..., None] if combined.ndim == 2 else combined)

    # Standard Phase 2 output family (consumed by phase2_rejection_checks.py)
    save_rgb(out_dir / 'adjusted_fg.png', relit_fg)
    save_rgb(out_dir / 'final_comp.png', final_comp)
    save_rgb(out_dir / 'delta.png', delta)
    save_rgb(out_dir / 'alpha_weighted_delta.png', alpha_weighted_delta)
    save_rgb(out_dir / 'raw_a_over_b.png', raw_over)
    Image.fromarray((np.clip(combined, 0, 1) * 255).astype(np.uint8)).save(out_dir / 'alpha_used.png')
    save_rgb(out_dir / 'ic_light_model_fg.png', model_fg)

    # Back-compat aliases (older comparison scripts referenced ic_flux_* names)
    save_rgb(out_dir / 'ic_flux_adjusted_fg.png', relit_fg)
    save_rgb(out_dir / 'ic_flux_final_comp.png', final_comp)
    save_rgb(out_dir / 'ic_flux_delta.png', delta)

    # Runtime block for the gate's runtime ceilings. duration_s = harmonization
    # compute only (pipeline load is a one-time cost, reported separately).
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    gpu_mem = {'cuda_available': bool(torch.cuda.is_available())}
    if torch.cuda.is_available():
        gpu_mem['max_reserved_mb'] = round(torch.cuda.max_memory_reserved() / (1024 ** 2), 2)
        gpu_mem['max_allocated_mb'] = round(torch.cuda.max_memory_allocated() / (1024 ** 2), 2)

    job = {
        'schema': 'latent-merge.phase1-run.v1',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'config': {
            'backend': f'ic_light_sd15_{args.ic_model}',
            'notes': 'SD1.5 IC-Light relight using official-style concat '
                     'conditioning. FBC uses grey-matted foreground plus plate '
                     'background latents; FC remains diagnostic only.',
            'base_model': SD15_NAME,
            'ic_light_model': f'iclight_sd15_{args.ic_model}',
            'prompt': args.prompt,
            'a_prompt': args.a_prompt,
            'n_prompt': args.n_prompt,
            'seed': args.seed, 'steps': args.steps, 'cfg': args.cfg,
            'infer_width': args.width, 'infer_height': args.height,
            'highres_scale': args.highres_scale,
            'highres_denoise': args.highres_denoise,
            'transfer_mode': args.transfer_mode,
            'transfer_strength': args.transfer_strength,
            'transfer_color_strength': args.transfer_color_strength,
            'transfer_blur_radius': args.transfer_blur_radius,
            'transfer_ratio_min': args.transfer_ratio_min,
            'transfer_ratio_max': args.transfer_ratio_max,
        },
        'inputs': {
            'plate_rgb': {'path': str(Path(args.plate).resolve()), 'sha256': _sha256(args.plate)},
            'cg_rgba':   {'path': str(Path(args.cg).resolve()),    'sha256': _sha256(args.cg)},
            'alpha':     {'path': str(Path(args.alpha).resolve()), 'sha256': _sha256(args.alpha)},
        },
        'outputs': {
            'adjusted_fg':          str((out_dir / 'adjusted_fg.png').resolve()),
            'final_comp':           str((out_dir / 'final_comp.png').resolve()),
            'delta':                str((out_dir / 'delta.png').resolve()),
            'alpha_weighted_delta': str((out_dir / 'alpha_weighted_delta.png').resolve()),
            'raw_a_over_b':         str((out_dir / 'raw_a_over_b.png').resolve()),
            'alpha_used':           str((out_dir / 'alpha_used.png').resolve()),
            'ic_light_model_fg':    str((out_dir / 'ic_light_model_fg.png').resolve()),
            'ic_light_fg_condition': str((out_dir / 'ic_light_fg_condition.png').resolve()),
            'ic_light_bg_condition': str((out_dir / 'ic_light_bg_condition.png').resolve()),
        },
        'runtime': {
            'duration_s': round(t_inf, 4),
            'pipeline_load_s': round(t_load, 4),
            'process_max_rss_mb': round(rss_mb, 2),
            'gpu_memory': gpu_mem,
        },
        'contract': {
            'plate_repainted': False,
            'primary_model_output': 'adjusted foreground RGB',
            'trusted_composite': 'normal A-over-B over original plate',
            'interaction_passes': [],
        },
    }
    with open(out_dir / 'job.json', 'w') as f:
        json.dump(job, f, indent=2)

    meta = {
        'technique': f'ic_light_sd15_{args.ic_model}',
        'prompt': args.prompt,
        'a_prompt': args.a_prompt,
        'n_prompt': args.n_prompt,
        'seed': args.seed,
        'steps': args.steps,
        'cfg': args.cfg,
        'width': args.width,
        'height': args.height,
        'highres_scale': args.highres_scale,
        'highres_denoise': args.highres_denoise,
        'transfer_mode': args.transfer_mode,
        'transfer_strength': args.transfer_strength,
        'transfer_color_strength': args.transfer_color_strength,
        'transfer_blur_radius': args.transfer_blur_radius,
        'transfer_ratio_min': args.transfer_ratio_min,
        'transfer_ratio_max': args.transfer_ratio_max,
        'model': SD15_NAME,
        'ic_light_model': f'iclight_sd15_{args.ic_model}',
    }
    with open(out_dir / 'meta.json', 'w') as f:
        json.dump(meta, f, indent=2)

    # Score it
    fg_mask = combined > 0.05
    fg_delta_mean = float(np.abs(relit_fg[fg_mask] - cg_rgb[fg_mask]).mean())
    mean_err_vs_plate = float(np.abs(relit_fg[fg_mask] - plate_rgb[fg_mask]).mean())
    final_std = float(final_comp[fg_mask].std())

    scores = {
        'technique': f'ic_light_sd15_{args.ic_model}',
        'fg_delta_mean': fg_delta_mean,
        'mean_err_vs_plate': mean_err_vs_plate,
        'final_std': final_std,
    }
    with open(out_dir / 'scores.json', 'w') as f:
        json.dump(scores, f, indent=2)

    print(f"\n✓ IC-Light done!")
    print(f"  fg_delta_mean: {fg_delta_mean:.6f}")
    print(f"  mean_err_vs_plate: {mean_err_vs_plate:.6f}")
    print(f"  final_std: {final_std:.6f}")
    print(f"  outputs → {out_dir}")

    return scores


if __name__ == '__main__':
    main()
