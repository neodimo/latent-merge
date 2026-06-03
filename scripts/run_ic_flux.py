#!/usr/bin/env python3
"""
IC Flux / IC-Light relighting runner for RTX 3080 Ti (12 GB VRAM).
Based on lllyasviel/IC-Light gradio_demo.py

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
from PIL import Image
from diffusers import StableDiffusionPipeline, StableDiffusionImg2ImgPipeline
from diffusers import AutoencoderKL, UNet2DConditionModel, DDIMScheduler, EulerAncestralDiscreteScheduler, DPMSolverMultistepScheduler
from diffusers.models.attention_processor import AttnProcessor2_0
from transformers import CLIPTextModel, CLIPTokenizer

# ── Config ────────────────────────────────────────────────────────────────────
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
SD15_NAME = 'stablediffusionapi/realistic-vision-v51'  # base SD15 model
IC_LIGHT_DIR = Path(__file__).parent.parent / 'weights' / 'ic-light-v2'
OUTPUT_DIR = Path('runs/overnight_harmonic_sweep/ic_flux')

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_rgb(path):
    return np.array(Image.open(path)).astype(np.float32) / 255.0

def load_rgba(path):
    a = np.array(Image.open(path))
    return a[:, :, :3].astype(np.float32) / 255.0, a[:, :, 3].astype(np.float32) / 255.0

def save_rgb(path, arr):
    Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8)).save(path)

def composite(fg, bg, a):
    a3 = a[..., None] if a.ndim == 2 else a
    return fg * a3 + bg * (1 - a3)

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

def setup_pipeline():
    print(f"Setting up IC-Light pipeline on {DEVICE}")
    print(f"Loading SD15 base model: {SD15_NAME} (will auto-download if not cached)")

    # Load tokenizer + text encoder
    tokenizer = CLIPTokenizer.from_pretrained(SD15_NAME, subfolder="tokenizer")
    text_encoder = CLIPTextModel.from_pretrained(SD15_NAME, subfolder="text_encoder")

    # Load VAE
    vae = AutoencoderKL.from_pretrained(SD15_NAME, subfolder="vae")

    # Load UNet
    unet = UNet2DConditionModel.from_pretrained(SD15_NAME, subfolder="unet")

    # Patch UNet conv_in to accept 8 channels (4 original + 4 from concat_conds)
    with torch.no_grad():
        new_conv_in = torch.nn.Conv2d(
            8, unet.conv_in.out_channels,
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
    model_path = IC_LIGHT_DIR / 'iclight_sd15_fc.safetensors'
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
    }


@torch.inference_mode()
def run_ic_light_relight(pipeline, fg_rgb, prompt, seed=42, steps=20, cfg=3.5,
                          image_width=768, image_height=432,
                          num_samples=1, a_prompt='', n_prompt=''):
    """
    Run IC-Light relighting on foreground RGB with text prompt.
    fg_rgb: HxWx3 numpy array in [0,1]
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

    # Prepare concat_conds (foreground encoding)
    fg_resized = resize_and_center_crop((fg_rgb * 255).astype(np.uint8), image_width, image_height)
    concat_conds = numpy2pytorch([fg_resized]).to(device=vae.device, dtype=vae.dtype)
    concat_conds = vae.encode(concat_conds).latent_dist.mode() * vae.config.scaling_factor

    rng = torch.Generator(device=device).manual_seed(int(seed))

    # Text-to-latent with foreground conditioning
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

    # Decode
    pixels = vae.decode(latents).sample
    pixels = pytorch2numpy(pixels)

    return pixels


def relight_with_composite(pipeline, plate_rgb, cg_rgb, alpha_2d, prompt,
                            seed=42, steps=20, cfg=3.5,
                            image_width=768, image_height=432,
                            a_prompt='cinematic, soft lighting, high quality',
                            n_prompt='overexposed, washed out, low contrast, blurry'):
    """
    Run IC-Light on the CG foreground, then composite over plate.
    Returns adjusted foreground (HxWx3) and final composite (HxWx3).
    """
    # Run IC-Light on CG foreground (no background)
    relit = run_ic_light_relight(
        pipeline, cg_rgb, prompt,
        seed=seed, steps=steps, cfg=cfg,
        image_width=image_width, image_height=image_height
    )
    relit_rgb = relit[0]  # HxWx3 in [0,1]

    # Composite relit foreground over plate using alpha
    final = composite(relit_rgb, plate_rgb, alpha_2d)

    return relit_rgb, final


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description='IC-Light relighting runner')
    parser.add_argument('--plate', required=True, help='Plate background PNG')
    parser.add_argument('--cg', required=True, help='CG foreground RGBA PNG')
    parser.add_argument('--alpha', required=True, help='Alpha mask PNG')
    parser.add_argument('--out-dir', default=str(OUTPUT_DIR), help='Output directory')
    parser.add_argument('--prompt', default='harmonize lighting, match plate illumination',
                        help='Relighting prompt')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--steps', type=int, default=20)
    parser.add_argument('--cfg', type=float, default=3.5)
    parser.add_argument('--width', type=int, default=768)
    parser.add_argument('--height', type=int, default=432)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Loading inputs...")
    plate_rgb = load_rgb(args.plate)
    cg_rgb, cg_alpha = load_rgba(args.cg)
    ext_alpha = load_rgb(args.alpha)
    combined = np.minimum(ext_alpha, cg_alpha)

    print(f"  plate: {plate_rgb.shape}, cg: {cg_rgb.shape}, alpha: {combined.shape}")
    print(f"  prompt: {args.prompt}")

    print("\nSetting up pipeline (downloading SD15 base if needed)...")
    pipeline = setup_pipeline()

    print(f"\nRunning IC-Light relighting (seed={args.seed}, steps={args.steps}, cfg={args.cfg})...")
    relit_fg, final_comp = relight_with_composite(
        pipeline, plate_rgb, cg_rgb, combined,
        prompt=args.prompt,
        seed=args.seed, steps=args.steps, cfg=args.cfg,
        image_width=args.width, image_height=args.height
    )

    # Save outputs
    save_rgb(out_dir / 'ic_flux_adjusted_fg.png', relit_fg)
    save_rgb(out_dir / 'ic_flux_final_comp.png', final_comp)
    delta = np.abs(relit_fg - cg_rgb)
    save_rgb(out_dir / 'ic_flux_delta.png', delta)

    meta = {
        'technique': 'ic_flux_relight',
        'prompt': args.prompt,
        'seed': args.seed,
        'steps': args.steps,
        'cfg': args.cfg,
        'width': args.width,
        'height': args.height,
        'model': SD15_NAME,
        'ic_light_model': 'iclight_sd15_fc',
    }
    with open(out_dir / 'meta.json', 'w') as f:
        json.dump(meta, f, indent=2)

    # Score it
    fg_mask = combined > 0.05
    fg_delta_mean = float(np.abs(relit_fg[fg_mask] - cg_rgb[fg_mask]).mean())
    mean_err_vs_plate = float(np.abs(relit_fg[fg_mask] - plate_rgb[fg_mask]).mean())
    final_std = float(final_comp[fg_mask].std())

    scores = {
        'technique': 'ic_flux_relight',
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