"""Validate the committed smoke-only Blender fixtures without modifying them.

Run with:
    blender --background --python scripts/validate_smoke_blender_fixtures.py
"""

from __future__ import annotations

import json
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "fixtures" / "smoke_blender_set"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def resolved_image_path(image: bpy.types.Image) -> Path:
    return Path(bpy.path.abspath(image.filepath)).resolve()


def validate_scene(entry: dict[str, str]) -> dict[str, object]:
    scene_path = ROOT / entry["scene"]
    require(scene_path.is_file(), f"missing scene: {scene_path}")
    bpy.ops.wm.open_mainfile(filepath=str(scene_path), load_ui=False)

    scene = bpy.context.scene
    camera = scene.camera
    require(camera is not None, f"{scene_path.name}: missing active camera")
    require(
        len(camera.data.background_images) > 0,
        f"{scene_path.name}: active camera has no plate background image",
    )

    plate_path = (ROOT / entry["plate"]).resolve()
    require(plate_path.is_file(), f"{scene_path.name}: missing plate: {plate_path}")
    camera_plates = {
        resolved_image_path(slot.image)
        for slot in camera.data.background_images
        if slot.image is not None
    }
    require(
        plate_path in camera_plates,
        f"{scene_path.name}: camera background does not use manifest plate",
    )

    world = scene.world
    require(
        world is not None and world.node_tree is not None,
        f"{scene_path.name}: missing node-based world",
    )
    environment_images = [
        node.image
        for node in world.node_tree.nodes
        if node.bl_idname == "ShaderNodeTexEnvironment" and node.image is not None
    ]
    require(environment_images, f"{scene_path.name}: missing HDRI environment")
    for image in environment_images:
        require(
            resolved_image_path(image).is_file(),
            f"{scene_path.name}: unresolved HDRI: {image.filepath}",
        )

    shadow_catchers = [
        obj.name
        for obj in scene.objects
        if obj.type == "MESH" and obj.is_shadow_catcher
    ]
    require(shadow_catchers, f"{scene_path.name}: missing mesh shadow catcher")

    cg_objects = [
        obj.name
        for obj in scene.objects
        if obj.type == "MESH" and obj.name.startswith("CG_")
    ]
    require(cg_objects, f"{scene_path.name}: missing named CG source objects")

    result: dict[str, object] = {
        "scene": entry["scene"],
        "plate": entry["plate"],
        "camera": camera.name,
        "cg_objects": cg_objects,
        "shadow_catchers": shadow_catchers,
        "hdri": [str(resolved_image_path(image)) for image in environment_images],
    }

    matte_entry = entry.get("matte")
    if matte_entry:
        matte_path = (ROOT / matte_entry).resolve()
        require(matte_path.is_file(), f"{scene_path.name}: missing matte: {matte_path}")
        occluders = [
            obj.name
            for obj in scene.objects
            if obj.type == "MESH" and "Occluder" in obj.name
        ]
        require(occluders, f"{scene_path.name}: missing foreground occlusion card")
        used_images = {
            resolved_image_path(node.image)
            for material in bpy.data.materials
            if material.node_tree is not None
            for node in material.node_tree.nodes
            if node.bl_idname == "ShaderNodeTexImage" and node.image is not None
        }
        require(
            matte_path in used_images,
            f"{scene_path.name}: occlusion card does not use manifest matte",
        )
        result["matte"] = matte_entry
        result["occluders"] = occluders

    return result


def main() -> None:
    require(MANIFEST_PATH.is_file(), f"missing manifest: {MANIFEST_PATH}")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    scenes = manifest.get("scenes", [])
    require(len(scenes) >= 2, "fixture manifest must contain at least two scenes")

    results = [validate_scene(entry) for entry in scenes]
    print("LATENT_MERGE_FIXTURE_VALIDATION " + json.dumps(results, sort_keys=True))
    print(f"PASS: validated {len(results)} smoke-only Blender fixtures")


if __name__ == "__main__":
    main()
