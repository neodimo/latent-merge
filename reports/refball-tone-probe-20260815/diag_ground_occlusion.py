import bpy, sys, math, json, numpy as np
sys.path.insert(0, "scripts")
import importlib.util
spec = importlib.util.spec_from_file_location("rci", "scripts/render_cg_insert.py")
rci = importlib.util.module_from_spec(spec); spec.loader.exec_module(rci)

HDR = "/tmp/lm_ground/work/urban_alley_01_4k.hdr"
res = {}
for mode in ("shadow_catcher", "matte_ground", "no_ground"):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    rci.setup_world(HDR)
    cam = rci.setup_camera(270.0, -6.0, 72.0, (0, 0, 1.6))
    bpy.context.view_layer.update()
    hit = rci.ground_hit_from_pixel(cam, 0.42, 0.88, 72.0, 1080/1920)
    if mode == "shadow_catcher":
        rci.add_ground(shadow_catcher=True)
    elif mode == "matte_ground":
        p = rci.add_ground(shadow_catcher=False)
        p.data.materials.append(rci._matte("road", 0.08))
    obj = rci.build_asset("gray_ball", 0.6)
    rci.rest_on_ground(obj, hit, target_height=0.6)
    out = f"/tmp/lm_ground/diag_{mode}.png"
    rci.render(out, 1920, 1080, 192, True)
    img = bpy.data.images.load(out)
    px = np.array(img.pixels[:]).reshape(1080, 1920, 4)[::-1]
    bpy.data.images.remove(img)
    m = px[..., 3] > 0.95
    L = 0.2126*px[...,0] + 0.7152*px[...,1] + 0.0722*px[...,2]
    ys, xs = np.nonzero(m)
    y0, y1 = ys.min(), ys.max()
    top = m.copy(); top[y0+(y1-y0)//3:] = False
    bot = m.copy(); bot[:y1-(y1-y0)//3] = False
    res[mode] = {"mean": float(L[m].mean()), "top": float(L[top].mean()),
                 "bottom": float(L[bot].mean()),
                 "top_over_bottom": round(float(L[top].mean()/max(L[bot].mean(),1e-9)), 3)}
print("OCCL " + json.dumps(res, indent=2))
