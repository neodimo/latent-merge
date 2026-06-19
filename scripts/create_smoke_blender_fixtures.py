"""Create smoke-only Blender fixtures for Phase 2 plumbing.

Run with:
    blender --background --python scripts/create_smoke_blender_fixtures.py

The scenes are intentionally simple and inspectable:
- real-life photography is used as the plate/background reference
- Poly Haven HDRI lights the CG
- CG casts shadows onto a shadow-catcher receiver
- the occlusion scene includes an explicit foreground matte card
"""

from __future__ import annotations

import json
import math
import os
import urllib.request
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "smoke_blender_set"
ASSETS = OUT / "assets"
SCENES = OUT / "scenes"

SOURCES = {
    "meeting_room_plate": {
        "url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Minimalist%20meeting%20room%20%28Unsplash%29.jpg",
        "path": ASSETS / "minimalist_meeting_room_unsplash.jpg",
        "credit": "Wikimedia Commons: File:Minimalist meeting room (Unsplash).jpg",
        "license": "Unsplash upload on Commons; verify file page before redistribution.",
    },
    "table_edge_plate": {
        "url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Photographer%27s%20table%20edge%20%28Unsplash%29.jpg",
        "path": ASSETS / "photographers_table_edge_unsplash.jpg",
        "credit": "Wikimedia Commons: File:Photographer's table edge (Unsplash).jpg",
        "license": "Unsplash upload on Commons; verify file page before redistribution.",
    },
    "studio_hdri": {
        "url": "https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/1k/studio_small_08_1k.hdr",
        "path": ASSETS / "studio_small_08_1k.hdr",
        "credit": "Poly Haven: studio_small_08",
        "license": "CC0",
    },
}


def ensure_dirs() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    SCENES.mkdir(parents=True, exist_ok=True)


def download_sources() -> None:
    for source in SOURCES.values():
        path = source["path"]
        if path.exists() and path.stat().st_size > 0:
            continue
        print(f"Downloading {source['url']} -> {path}")
        req = urllib.request.Request(source["url"], headers={"User-Agent": "latent-merge-fixture/0.1"})
        with urllib.request.urlopen(req, timeout=60) as response:
            path.write_bytes(response.read())


def reset_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    bpy.context.scene.frame_set(1)


def look_at(obj: bpy.types.Object, target: tuple[float, float, float]) -> None:
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def setup_camera(plate_path: Path, lens_mm: float = 35.0) -> bpy.types.Object:
    bpy.ops.object.camera_add(location=(0.0, -6.4, 2.45), rotation=(math.radians(68), 0.0, 0.0))
    camera = bpy.context.object
    camera.name = "Plate_Match_Camera"
    camera.data.lens = lens_mm
    camera.data.display_size = 0.45
    bpy.context.scene.camera = camera

    bg = camera.data.background_images.new()
    bg.image = bpy.data.images.load(str(plate_path), check_existing=True)
    bg.alpha = 1.0
    bg.display_depth = "BACK"
    bg.frame_method = "CROP"
    camera.data.show_background_images = True
    return camera


def set_render_defaults() -> None:
    scene = bpy.context.scene
    bpy.context.preferences.filepaths.save_version = 0
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 96
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 720
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "Medium High Contrast"
    scene.view_settings.exposure = 0.0
    scene.view_settings.gamma = 1.0
    scene.world = bpy.data.worlds.new("HDRI_World")
    scene.world.color = (0.03, 0.03, 0.03)


def set_hdri(path: Path, strength: float, rotation_degrees: float) -> None:
    world = bpy.context.scene.world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()

    tex_coord = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    env = nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(str(path), check_existing=True)
    bg = nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = strength
    output = nodes.new("ShaderNodeOutputWorld")
    mapping.inputs["Rotation"].default_value[2] = math.radians(rotation_degrees)

    links.new(tex_coord.outputs["Generated"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], env.inputs["Vector"])
    links.new(env.outputs["Color"], bg.inputs["Color"])
    links.new(bg.outputs["Background"], output.inputs["Surface"])


def make_material(name: str, color: tuple[float, float, float, float], roughness: float = 0.5, metallic: float = 0.0) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    return material


def make_shadow_catcher(name: str, location: tuple[float, float, float], scale: tuple[float, float, float]) -> bpy.types.Object:
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=location)
    receiver = bpy.context.object
    receiver.name = name
    receiver.scale = scale
    receiver.is_shadow_catcher = True
    receiver.display_type = "TEXTURED"
    receiver.data.materials.append(make_material("Matte_Shadow_Catcher_Guide", (0.52, 0.49, 0.43, 0.35), 0.85))
    return receiver


def add_area_key(name: str, location: tuple[float, float, float], target: tuple[float, float, float], power: float, size: float) -> None:
    bpy.ops.object.light_add(type="AREA", location=location)
    light = bpy.context.object
    light.name = name
    light.data.energy = power
    light.data.size = size
    look_at(light, target)


def add_plate_reference_plane(name: str, plate_path: Path, location: tuple[float, float, float], scale: tuple[float, float, float]) -> None:
    image = bpy.data.images.load(str(plate_path), check_existing=True)
    material = bpy.data.materials.new(f"{name}_Emission_Material")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = image
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Strength"].default_value = 0.7
    out = nodes.new("ShaderNodeOutputMaterial")
    links.new(tex.outputs["Color"], emission.inputs["Color"])
    links.new(emission.outputs["Emission"], out.inputs["Surface"])

    bpy.ops.mesh.primitive_plane_add(size=1.0, location=location, rotation=(math.radians(90), 0.0, 0.0))
    plane = bpy.context.object
    plane.name = name
    plane.scale = scale
    plane.data.materials.append(material)


def add_cg_marker_stack() -> None:
    red = make_material("CG_Red_Rough_Plastic", (0.95, 0.12, 0.07, 1.0), 0.38)
    chrome = make_material("CG_Brushed_Chrome", (0.78, 0.82, 0.85, 1.0), 0.24, 0.85)
    dark = make_material("CG_Dark_Rubber", (0.025, 0.024, 0.022, 1.0), 0.62)

    bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=48, radius=0.42, location=(-0.38, -0.12, 0.42))
    sphere = bpy.context.object
    sphere.name = "CG_Foreground_Sphere_RGBA_Source"
    sphere.data.materials.append(red)

    bpy.ops.mesh.primitive_torus_add(major_radius=0.44, minor_radius=0.055, major_segments=96, minor_segments=16, location=(0.38, 0.0, 0.48))
    torus = bpy.context.object
    torus.name = "CG_Chrome_Ring_RGBA_Source"
    torus.rotation_euler[1] = math.radians(72)
    torus.data.materials.append(chrome)

    bpy.ops.mesh.primitive_cube_add(size=0.72, location=(0.08, 0.18, 0.09))
    base = bpy.context.object
    base.name = "CG_Dark_Base_RGBA_Source"
    base.scale = (1.55, 0.44, 0.16)
    base.data.materials.append(dark)


def create_foreground_matte_image(path: Path) -> Path:
    image = bpy.data.images.new("table_edge_foreground_segmentation_matte", 1280, 720, alpha=True, float_buffer=False)
    pixels: list[float] = []
    for y in range(720):
        for x in range(1280):
            # A rough table-edge foreground holdout: opaque at bottom, feathered near the top edge.
            edge = 468 + int(35 * math.sin((x / 1280.0) * math.pi))
            if y < edge:
                alpha = 0.0
            else:
                alpha = min(1.0, (y - edge) / 48.0)
            pixels.extend((0.0, 0.0, 0.0, alpha))
    image.pixels[:] = pixels
    image.filepath_raw = str(path)
    image.file_format = "PNG"
    image.save()
    return path


def add_occlusion_card(matte_path: Path) -> None:
    matte = bpy.data.images.load(str(matte_path), check_existing=True)
    material = bpy.data.materials.new("Segmentation_Level_Matte_Holdout_Material")
    material.use_nodes = True
    material.blend_method = "BLEND"
    material.show_transparent_back = True

    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = matte
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    holdout = nodes.new("ShaderNodeBsdfDiffuse")
    holdout.inputs["Color"].default_value = (0.18, 0.16, 0.14, 1.0)
    mix = nodes.new("ShaderNodeMixShader")
    out = nodes.new("ShaderNodeOutputMaterial")
    links.new(tex.outputs["Alpha"], mix.inputs["Fac"])
    links.new(transparent.outputs["BSDF"], mix.inputs[1])
    links.new(holdout.outputs["BSDF"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])

    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.0, -1.55, 0.7), rotation=(math.radians(75), 0.0, 0.0))
    card = bpy.context.object
    card.name = "Segmentation_Matte_Foreground_Occluder_Table_Edge"
    card.scale = (3.4, 1.9, 1.0)
    card.data.materials.append(material)
    card.show_name = True


def add_occluded_cg() -> None:
    teal = make_material("CG_Teal_Ceramic", (0.0, 0.7, 0.66, 1.0), 0.31)
    brass = make_material("CG_Warm_Metal", (0.95, 0.67, 0.25, 1.0), 0.22, 0.55)

    bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=48, radius=0.34, location=(-0.18, -0.08, 0.36))
    body = bpy.context.object
    body.name = "CG_Occluded_Sphere_RGBA_Source"
    body.data.materials.append(teal)

    bpy.ops.mesh.primitive_cone_add(vertices=64, radius1=0.19, radius2=0.07, depth=0.55, location=(0.35, -0.05, 0.39))
    cone = bpy.context.object
    cone.name = "CG_Occluded_Cone_RGBA_Source"
    cone.rotation_euler[0] = math.radians(8)
    cone.data.materials.append(brass)

    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.24, depth=0.06, location=(0.05, 0.08, 0.05))
    foot = bpy.context.object
    foot.name = "CG_Contact_Foot_RGBA_Source"
    foot.data.materials.append(brass)


def annotate_scene(scene_name: str, notes: list[str]) -> None:
    text_curve = bpy.data.curves.new("Fixture_Notes", type="FONT")
    text_curve.body = scene_name + "\n" + "\n".join(f"- {note}" for note in notes)
    text_curve.size = 0.08
    text_curve.align_x = "LEFT"
    text_curve.align_y = "TOP"
    text_obj = bpy.data.objects.new("Fixture_Notes_Readme", text_curve)
    text_obj.location = (-1.75, 1.35, 1.2)
    text_obj.rotation_euler = (math.radians(72), 0.0, 0.0)
    text_obj.hide_render = True
    bpy.context.collection.objects.link(text_obj)


def save_scene(path: Path) -> None:
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    bpy.ops.file.make_paths_relative()
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    print(f"Saved {path}")


def build_meeting_room_scene() -> dict[str, str]:
    reset_scene()
    set_render_defaults()
    set_hdri(SOURCES["studio_hdri"]["path"], strength=0.95, rotation_degrees=28)
    setup_camera(SOURCES["meeting_room_plate"]["path"], lens_mm=31)
    add_plate_reference_plane("Real_Plate_Backdrop_Minimalist_Meeting_Room", SOURCES["meeting_room_plate"]["path"], (0.0, 1.35, 1.2), (6.6, 3.7, 1.0))
    make_shadow_catcher("Shadow_Catcher_Table_or_Floor_Receiver", (0.0, 0.0, 0.0), (2.4, 1.5, 1.0))
    add_area_key("Window_Matched_Soft_Key", (-2.4, -3.3, 4.1), (0.0, 0.0, 0.25), 340.0, 4.0)
    add_area_key("Weak_Warm_Practical_Fill", (2.0, -2.0, 2.2), (0.0, 0.0, 0.25), 55.0, 2.2)
    add_cg_marker_stack()
    annotate_scene(
        "real_plate_meeting_room_shadow",
        [
            "real photo plate is camera background and backdrop plane",
            "CG source objects cast onto named shadow catcher",
            "HDRI world: studio_small_08_1k.hdr with added matched key/fill lights",
        ],
    )
    path = SCENES / "real_plate_meeting_room_shadow.blend"
    save_scene(path)
    return {"scene": str(path.relative_to(ROOT)), "plate": str(SOURCES["meeting_room_plate"]["path"].relative_to(ROOT))}


def build_table_edge_scene() -> dict[str, str]:
    reset_scene()
    set_render_defaults()
    set_hdri(SOURCES["studio_hdri"]["path"], strength=1.1, rotation_degrees=-44)
    setup_camera(SOURCES["table_edge_plate"]["path"], lens_mm=45)
    add_plate_reference_plane("Real_Plate_Backdrop_Photographers_Table_Edge", SOURCES["table_edge_plate"]["path"], (0.0, 1.25, 1.15), (6.6, 3.7, 1.0))
    make_shadow_catcher("Shadow_Catcher_Table_Surface_Receiver", (0.0, 0.0, 0.0), (2.2, 1.25, 1.0))
    add_area_key("Plate_Left_Window_Soft_Key", (-1.9, -3.1, 3.2), (0.0, 0.0, 0.24), 280.0, 3.6)
    add_occluded_cg()
    matte_path = create_foreground_matte_image(ASSETS / "table_edge_foreground_segmentation_matte.png")
    add_occlusion_card(matte_path)
    annotate_scene(
        "real_plate_table_edge_occlusion",
        [
            "real photo plate is camera background and backdrop plane",
            "foreground table-edge matte card demonstrates plate occlusion",
            "CG source objects sit behind matte and cast shadows to receiver",
            "HDRI world: studio_small_08_1k.hdr with matched soft key",
        ],
    )
    path = SCENES / "real_plate_table_edge_occlusion.blend"
    save_scene(path)
    return {
        "scene": str(path.relative_to(ROOT)),
        "plate": str(SOURCES["table_edge_plate"]["path"].relative_to(ROOT)),
        "matte": str(matte_path.relative_to(ROOT)),
    }


def write_manifest(scene_entries: list[dict[str, str]]) -> None:
    manifest = {
        "purpose": "Real-photo plate Blender fixtures for Phase 2 Layer-1/Layer-2 intake.",
        "blocked_requirement": "Use real-life photography as plate, add CG with HDRI lighting, shadow interaction, and segmentation-level matte occlusion when foreground objects overlap CG.",
        "sources": {
            name: {
                "url": str(source["url"]),
                "path": str(source["path"].relative_to(ROOT)),
                "credit": source["credit"],
                "license": source["license"],
            }
            for name, source in SOURCES.items()
        },
        "scenes": scene_entries,
        "open_in_blender": [
            "fixtures/smoke_blender_set/scenes/smoke_meeting_room_shadow.blend",
            "fixtures/smoke_blender_set/scenes/smoke_table_edge_occlusion.blend",
        ],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    ensure_dirs()
    download_sources()
    entries = [build_meeting_room_scene(), build_table_edge_scene()]
    write_manifest(entries)


if __name__ == "__main__":
    main()
