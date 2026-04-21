import argparse
import csv
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

try:
    from rapidocr_onnxruntime import RapidOCR
except Exception:
    RapidOCR = None

try:
    import mss
except Exception:
    mss = None

try:
    import pygetwindow as gw
except Exception:
    gw = None


if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"
REPORT_PATH = ROOT / "report.csv"
ASSETS_DIR = ROOT / "assets"
ICON_TEMPLATE = ASSETS_DIR / "pollution_icon.png"
SPECIES_TEMPLATE_DIR = ASSETS_DIR / "species_templates"
ATTRIBUTE_TEMPLATE_DIR = ASSETS_DIR / "attribute_templates"
SPECIES_ATTRIBUTE_PATH = ROOT / "species_attributes.json"


@dataclass
class ParseResult:
    pollution: int
    reason: str
    ocr_text: str
    matched_file: str
    icon_score: float = 0.0
    purple_ratio: float = 0.0


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def read_image(path: Path) -> Optional[np.ndarray]:
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception:
        return None


def write_image(path: Path, image: np.ndarray) -> bool:
    try:
        ext = path.suffix if path.suffix else ".png"
        ok, buf = cv2.imencode(ext, image)
        if not ok:
            return False
        buf.tofile(str(path))
        return True
    except Exception:
        return False


def default_config() -> Dict:
    return {
        "watch_dir": "E:/code/screenshots",
        "poll_interval_sec": 2,
        "image_exts": [".png", ".jpg", ".jpeg", ".bmp", ".webp"],
        "icon_mode": {
            "enabled": True,
            "use_template": True,
            "template_path": str(ICON_TEMPLATE),
            "icon_pollution_value": 1,
            "template_match_threshold": 0.72,
            "purple_ratio_threshold": 0.22,
            "enable_lowlight_boost": True,
            "lowlight_v_gain": 1.18,
            "lowlight_clahe_clip": 2.2,
            "template_scales": [0.88, 0.94, 1.0, 1.06, 1.12],
            "enable_dark_scene_adaptive_threshold": True,
            "dark_scene_v_threshold": 92.0,
            "dark_scene_score_relax_max": 0.12,
            "dark_scene_purple_relax_max": 0.08,
            "dark_scene_score_floor": 0.62,
            "dark_scene_purple_floor": 0.14,
            "enable_mask_iou_gate": True,
            "mask_iou_threshold": 0.16,
            "mask_iou_dark_relax_max": 0.08,
            "mask_iou_dark_floor": 0.08,
            "mask_iou_bypass_score_margin": 0.08,
            "purple_blob_min_area": 220,
            "purple_blob_max_area": 18000,
            "purple_blob_min_fill": 0.22,
            "blob_process_scale": 0.6,
            "blob_max_width": 1280,
            "hsv_ranges": [
                [125, 50, 35, 179, 255, 255]
            ]
        },
        "ocr_mode": {
            "enabled": False,
            "count_fail": True,
            "success_pollution": 1,
            "fail_pollution": 1,
            "keywords": {
                "success": ["捕捉成功", "捕获成功", "成功捕捉"],
                "fail": ["捕捉失败", "捕获失败", "未捕捉到", "逃跑了"]
            },
            "pollution_regexes": [
                "污染\\s*[+：:]?\\s*(\\d+)",
                "污染值\\s*[+：:]?\\s*(\\d+)",
                "污染增加\\s*(\\d+)",
                "污染\\s*\\+\\s*(\\d+)"
            ]
        },
        "screen_mode": {
            "enabled": True,
            "capture_interval_sec": 0.7,
            "window_title_contains": "洛克王国",
            "monitor_index": 1,
            "present_confirm_frames": 2,
            "absent_confirm_frames": 2,
            "min_trigger_gap_sec": 1.2,
            "rearm_absent_sec": 3.0,
        },
        "name_mode": {
            "enabled": True,
            "species_db_path": str(ROOT / "species_names.json"),
            "fuzzy_threshold": 0.62,
            "require_name_match": True,
            "prefer_ocr_name_first": True,
            "min_ocr_text_length": 2,
            "ocr_interval_sec": 0.9,
            "cache_ttl_sec": 2.4,
            "region": {
                "x_ratio": 0.79,
                "y_ratio": 0.015,
                "w_ratio": 0.16,
                "h_ratio": 0.085,
            },
        },
        "species_template_mode": {
            "enabled": True,
            "template_dir": str(SPECIES_TEMPLATE_DIR),
            "match_threshold": 0.58,
            "purple_ratio_threshold": 0.18,
            "enable_mask_iou_gate": False,
            "debug_best_min_score": 0.58,
            "second_best_margin": 0.06,
            "local_track_enabled": True,
            "local_track_expand_ratio": 1.8,
            "full_scan_interval_sec": 1.2,
        },
        "attribute_mode": {
            "enabled": True,
            "template_dir": str(ATTRIBUTE_TEMPLATE_DIR),
            "species_attribute_map_path": str(SPECIES_ATTRIBUTE_PATH),
            "min_match_score": 0.62,
            "require_species_map": True,
            "require_attribute_template": True,
            "scales": [0.9, 1.0, 1.1],
            "roi": {
                "x_ratio": -0.42,
                "y_ratio": 0.52,
                "w_ratio": 0.62,
                "h_ratio": 0.56,
            },
        },
    }


def merge_defaults(cfg: Dict, defaults: Dict) -> Dict:
    out = dict(defaults)
    for k, v in cfg.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            child = dict(out[k])
            child.update(v)
            out[k] = child
        else:
            out[k] = v
    return out


def init_files():
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    SPECIES_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    ATTRIBUTE_TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)

    cfg = load_json(CONFIG_PATH, None)
    if cfg is None:
        cfg = default_config()
    else:
        cfg = merge_defaults(cfg, default_config())
    save_json(CONFIG_PATH, cfg)

    st = load_json(STATE_PATH, None)
    if st is None:
        st = {"total_pollution": 0, "processed_hashes": {}, "records": [], "pet_pool": {}}
        save_json(STATE_PATH, st)
    else:
        st.setdefault("pet_pool", {})
        save_json(STATE_PATH, st)

    if not REPORT_PATH.exists():
        with REPORT_PATH.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["time", "file", "pollution", "reason", "icon_score", "purple_ratio", "ocr_text"]
            )

    readme = ASSETS_DIR / "README.txt"
    if not readme.exists():
        readme.write_text(
            "把污染图标截图保存为 pollution_icon.png 到这个目录。\n"
            "建议使用原始截图直接裁切图标区域，避免压缩失真。\n",
            encoding="utf-8",
        )

    species_readme = SPECIES_TEMPLATE_DIR / "README.txt"
    if not species_readme.exists():
        species_readme.write_text(
            "把每种精灵第一次遇到时的污染头像截图放到这里。\n"
            "文件名就是精灵名，例如：机械方方.png、筛晨.png\n"
            "建议只截左侧污染头像区域，尽量不要带整条血条和界面其它文字。\n",
            encoding="utf-8",
        )

    attr_readme = ATTRIBUTE_TEMPLATE_DIR / "README.txt"
    if not attr_readme.exists():
        attr_readme.write_text(
            "将属性小图标单独截图放在这里，文件名就是属性名，例如：冰.png、水.png、火.png。\n"
            "建议截图尺寸 24~48 像素，背景尽量干净。\n",
            encoding="utf-8",
        )

    if not SPECIES_ATTRIBUTE_PATH.exists():
        SPECIES_ATTRIBUTE_PATH.write_text(
            json.dumps({}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def image_sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run_ocr(engine, image_path: Path) -> str:
    if engine is None:
        return ""
    out = engine(str(image_path))
    if not out or not isinstance(out, tuple) or not out[0]:
        return ""
    lines = []
    for item in out[0]:
        try:
            txt = item[1]
            if txt:
                lines.append(str(txt))
        except Exception:
            continue
    return "\n".join(lines)


def run_ocr_on_bgr(engine, frame_bgr: np.ndarray) -> str:
    if engine is None:
        return ""
    if frame_bgr is None or frame_bgr.size == 0:
        return ""
    ok, buf = cv2.imencode(".png", frame_bgr)
    if not ok:
        return ""
    out = engine(buf.tobytes())
    if not out or not isinstance(out, tuple) or not out[0]:
        return ""
    lines = []
    for item in out[0]:
        try:
            txt = item[1]
            if txt:
                lines.append(str(txt))
        except Exception:
            continue
    return "\n".join(lines)


def normalize_species_name_text(text: str) -> str:
    if not text:
        return ""
    return "".join(ch for ch in str(text) if ("\u4e00" <= ch <= "\u9fff") or ch.isalnum())


def similarity_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return float(SequenceMatcher(None, a, b).ratio())


def extract_pollution_from_text(ocr_text: str, ocr_cfg: Dict) -> Tuple[int, str]:
    text = ocr_text or ""
    for pat in ocr_cfg.get("pollution_regexes", []):
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1)), f"ocr-regex:{pat}"
            except Exception:
                continue

    succ = ocr_cfg.get("keywords", {}).get("success", [])
    fail = ocr_cfg.get("keywords", {}).get("fail", [])

    if any(k in text for k in succ):
        return int(ocr_cfg.get("success_pollution", 1)), "ocr-keyword:success"
    if any(k in text for k in fail):
        if ocr_cfg.get("count_fail", False):
            return int(ocr_cfg.get("fail_pollution", 0)), "ocr-keyword:fail"
        return 0, "ocr-keyword:fail(skip)"

    return 0, "ocr-no-match"


def _purple_ratio(bgr_region: np.ndarray, hsv_ranges: List[List[int]]) -> float:
    if bgr_region.size == 0:
        return 0.0
    hsv = cv2.cvtColor(bgr_region, cv2.COLOR_BGR2HSV)
    merged_mask = None
    for r in hsv_ranges:
        if len(r) != 6:
            continue
        low = np.array(r[:3], dtype=np.uint8)
        high = np.array(r[3:], dtype=np.uint8)
        mask = cv2.inRange(hsv, low, high)
        merged_mask = mask if merged_mask is None else cv2.bitwise_or(merged_mask, mask)
    if merged_mask is None:
        return 0.0
    return float(np.count_nonzero(merged_mask)) / float(merged_mask.size)


def _purple_mask_from_hsv(hsv_img: np.ndarray, hsv_ranges: List[List[int]]) -> Optional[np.ndarray]:
    merged_mask = None
    for r in hsv_ranges:
        if len(r) != 6:
            continue
        low = np.array(r[:3], dtype=np.uint8)
        high = np.array(r[3:], dtype=np.uint8)
        mask = cv2.inRange(hsv_img, low, high)
        merged_mask = mask if merged_mask is None else cv2.bitwise_or(merged_mask, mask)
    return merged_mask


def _boost_lowlight_bgr(bgr_img: np.ndarray, icon_cfg: Dict) -> np.ndarray:
    if bgr_img is None or bgr_img.size == 0 or not bool(icon_cfg.get("enable_lowlight_boost", True)):
        return bgr_img
    hsv = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2HSV)
    h, s, v = cv2.split(hsv)
    clip = float(icon_cfg.get("lowlight_clahe_clip", 2.2))
    gain = float(icon_cfg.get("lowlight_v_gain", 1.18))
    clahe = cv2.createCLAHE(clipLimit=max(1.0, clip), tileGridSize=(8, 8))
    v = clahe.apply(v)
    if abs(gain - 1.0) > 1e-3:
        v = np.clip(v.astype(np.float32) * gain, 0, 255).astype(np.uint8)
    boosted = cv2.merge((h, s, v))
    return cv2.cvtColor(boosted, cv2.COLOR_HSV2BGR)


def _adaptive_thresholds(frame_bgr: np.ndarray, icon_cfg: Dict) -> Tuple[float, float, float]:
    score_th = float(icon_cfg.get("template_match_threshold", 0.55))
    purple_th = float(icon_cfg.get("purple_ratio_threshold", 0.12))
    if frame_bgr is None or frame_bgr.size == 0:
        return score_th, purple_th, 255.0
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    mean_v = float(np.mean(hsv[:, :, 2]))
    if not bool(icon_cfg.get("enable_dark_scene_adaptive_threshold", True)):
        return score_th, purple_th, mean_v
    dark_v = float(icon_cfg.get("dark_scene_v_threshold", 92.0))
    if mean_v >= dark_v:
        return score_th, purple_th, mean_v

    darkness = max(0.0, min(1.0, (dark_v - mean_v) / max(dark_v, 1.0)))
    score_relax_max = float(icon_cfg.get("dark_scene_score_relax_max", 0.12))
    purple_relax_max = float(icon_cfg.get("dark_scene_purple_relax_max", 0.08))
    score_floor = float(icon_cfg.get("dark_scene_score_floor", 0.62))
    purple_floor = float(icon_cfg.get("dark_scene_purple_floor", 0.14))
    score_th = max(score_floor, score_th - score_relax_max * darkness)
    purple_th = max(purple_floor, purple_th - purple_relax_max * darkness)
    return score_th, purple_th, mean_v


def _mask_iou(mask_a: Optional[np.ndarray], mask_b: Optional[np.ndarray]) -> float:
    if mask_a is None or mask_b is None:
        return 0.0
    if mask_a.shape != mask_b.shape:
        return 0.0
    a = mask_a > 0
    b = mask_b > 0
    union = np.count_nonzero(a | b)
    if union <= 0:
        return 0.0
    inter = np.count_nonzero(a & b)
    return float(inter) / float(union)


def _adaptive_iou_threshold(mean_v: float, icon_cfg: Dict) -> float:
    base = float(icon_cfg.get("mask_iou_threshold", 0.16))
    if not bool(icon_cfg.get("enable_dark_scene_adaptive_threshold", True)):
        return base
    dark_v = float(icon_cfg.get("dark_scene_v_threshold", 92.0))
    if mean_v >= dark_v:
        return base
    darkness = max(0.0, min(1.0, (dark_v - mean_v) / max(dark_v, 1.0)))
    relax = float(icon_cfg.get("mask_iou_dark_relax_max", 0.08))
    floor = float(icon_cfg.get("mask_iou_dark_floor", 0.08))
    return max(floor, base - relax * darkness)


def _bbox_iou(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1 = max(ax, bx)
    iy1 = max(ay, by)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = aw * ah + bw * bh - inter
    if union <= 0:
        return 0.0
    return float(inter) / float(union)


def _collect_match_candidates(
    frame_bgr: np.ndarray, template_bgr: np.ndarray, icon_cfg: Dict
) -> List[Dict]:
    scales = icon_cfg.get("template_scales", [1.0]) or [1.0]
    topk_per_scale = int(icon_cfg.get("template_topk_per_scale", 5))
    max_candidates = int(icon_cfg.get("template_max_candidates", 18))
    ih, iw = frame_bgr.shape[:2]
    cands: List[Dict] = []
    for scale in scales:
        try:
            scale = float(scale)
        except Exception:
            continue
        if scale <= 0:
            continue
        if abs(scale - 1.0) < 1e-3:
            scaled = template_bgr
        else:
            tw = max(8, int(round(template_bgr.shape[1] * scale)))
            th = max(8, int(round(template_bgr.shape[0] * scale)))
            scaled = cv2.resize(template_bgr, (tw, th), interpolation=cv2.INTER_LINEAR)
        th, tw = scaled.shape[:2]
        if ih < th or iw < tw:
            continue

        result = cv2.matchTemplate(frame_bgr, scaled, cv2.TM_CCOEFF_NORMED)
        if result is None or result.size == 0:
            continue
        flat = result.reshape(-1)
        k = min(max(1, topk_per_scale), flat.size)
        idxs = np.argpartition(flat, -k)[-k:]
        idxs = idxs[np.argsort(flat[idxs])[::-1]]
        rw = result.shape[1]
        for idx in idxs:
            y = int(idx // rw)
            x = int(idx % rw)
            cands.append(
                {
                    "score": float(result[y, x]),
                    "x": x,
                    "y": y,
                    "w": tw,
                    "h": th,
                    "template": scaled,
                }
            )

    if not cands:
        return []

    cands.sort(key=lambda z: z["score"], reverse=True)
    keep: List[Dict] = []
    iou_nms = float(icon_cfg.get("template_candidate_iou_nms", 0.70))
    for c in cands:
        box = (c["x"], c["y"], c["w"], c["h"])
        conflict = False
        for k in keep:
            if _bbox_iou(box, (k["x"], k["y"], k["w"], k["h"])) >= iou_nms:
                conflict = True
                break
        if conflict:
            continue
        keep.append(c)
        if len(keep) >= max(1, max_candidates):
            break
    return keep


def _detect_purple_icon_from_frame_template(
    frame_bgr: np.ndarray, icon_cfg: Dict, template_bgr: np.ndarray
) -> Tuple[bool, float, float, str, Tuple[int, int, int, int]]:
    if frame_bgr is None or frame_bgr.size == 0:
        return False, 0.0, 0.0, "icon-empty-frame", (0, 0, 0, 0)
    if template_bgr is None or template_bgr.size == 0:
        return False, 0.0, 0.0, "icon-template-invalid", (0, 0, 0, 0)

    match_frame = _boost_lowlight_bgr(frame_bgr, icon_cfg)
    score_th, purple_th, mean_v = _adaptive_thresholds(match_frame, icon_cfg)
    iou_th = _adaptive_iou_threshold(mean_v, icon_cfg)
    bypass_margin = float(icon_cfg.get("mask_iou_bypass_score_margin", 0.08))

    candidates = _collect_match_candidates(match_frame, template_bgr, icon_cfg)
    if not candidates:
        return False, 0.0, 0.0, "icon-template-too-large", (0, 0, 0, 0)

    best_any = None
    best_hit = None
    for cand in candidates:
        x, y, tw, th = cand["x"], cand["y"], cand["w"], cand["h"]
        region = match_frame[y : y + th, x : x + tw]
        if region.size == 0:
            continue
        purple_ratio = _purple_ratio(region, icon_cfg.get("hsv_ranges", []))
        tmpl_scaled = cand["template"]
        region_hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        tmpl_hsv = cv2.cvtColor(tmpl_scaled, cv2.COLOR_BGR2HSV)
        region_mask = _purple_mask_from_hsv(region_hsv, icon_cfg.get("hsv_ranges", []))
        tmpl_mask = _purple_mask_from_hsv(tmpl_hsv, icon_cfg.get("hsv_ranges", []))
        iou = _mask_iou(region_mask, tmpl_mask)

        iou_pass = True
        if bool(icon_cfg.get("enable_mask_iou_gate", True)):
            iou_pass = (iou >= iou_th) or (cand["score"] >= score_th + bypass_margin)
        hit = (cand["score"] >= score_th) and (purple_ratio >= purple_th) and iou_pass

        sn = cand["score"] / max(score_th, 1e-6)
        pn = purple_ratio / max(purple_th, 1e-6)
        inn = iou / max(iou_th, 1e-6)
        composite = 0.58 * sn + 0.24 * pn + 0.18 * inn
        item = {
            "hit": hit,
            "score": float(cand["score"]),
            "purple": float(purple_ratio),
            "iou": float(iou),
            "x": int(x),
            "y": int(y),
            "w": int(tw),
            "h": int(th),
            "composite": float(composite),
        }

        if best_any is None or item["composite"] > best_any["composite"]:
            best_any = item
        if hit and (best_hit is None or item["composite"] > best_hit["composite"]):
            best_hit = item

    chosen = best_hit if best_hit is not None else best_any
    if chosen is None:
        return False, 0.0, 0.0, "icon-no-candidate", (0, 0, 0, 0)

    ok = bool(chosen["hit"])
    reason = (
        f"icon(score={chosen['score']:.3f},purple={chosen['purple']:.3f},iou={chosen['iou']:.3f},"
        f"size={chosen['w']}x{chosen['h']},v={mean_v:.1f},cmp={chosen['composite']:.3f},"
        f"th={score_th:.3f}/{purple_th:.3f}/{iou_th:.3f})"
    )
    return (
        ok,
        float(chosen["score"]),
        float(chosen["purple"]),
        reason,
        (int(chosen["x"]), int(chosen["y"]), int(chosen["w"]), int(chosen["h"])),
    )


def _match_template_multiscale(
    frame_bgr: np.ndarray, template_bgr: np.ndarray, icon_cfg: Dict
) -> Tuple[float, Tuple[int, int], Tuple[int, int], np.ndarray]:
    best_score = -1.0
    best_loc = (0, 0)
    best_size = (0, 0)
    best_template = template_bgr
    scales = icon_cfg.get("template_scales", [1.0]) or [1.0]
    ih, iw = frame_bgr.shape[:2]
    for scale in scales:
        try:
            scale = float(scale)
        except Exception:
            continue
        if scale <= 0:
            continue
        if abs(scale - 1.0) < 1e-3:
            scaled = template_bgr
        else:
            tw = max(8, int(round(template_bgr.shape[1] * scale)))
            th = max(8, int(round(template_bgr.shape[0] * scale)))
            scaled = cv2.resize(template_bgr, (tw, th), interpolation=cv2.INTER_LINEAR)
        th, tw = scaled.shape[:2]
        if ih < th or iw < tw:
            continue
        result = cv2.matchTemplate(frame_bgr, scaled, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val > best_score:
            best_score = float(max_val)
            best_loc = max_loc
            best_size = (tw, th)
            best_template = scaled
    return best_score, best_loc, best_size, best_template


def crop_template_to_icon(template_bgr: np.ndarray, icon_cfg: Dict) -> np.ndarray:
    """
    If user provided a large template (icon + name + hp bar), auto-crop it to the dominant purple icon blob.
    """
    if template_bgr is None or template_bgr.size == 0:
        return template_bgr
    hsv = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2HSV)
    merged_mask = None
    for r in icon_cfg.get("hsv_ranges", []):
        if len(r) != 6:
            continue
        low = np.array(r[:3], dtype=np.uint8)
        high = np.array(r[3:], dtype=np.uint8)
        m = cv2.inRange(hsv, low, high)
        merged_mask = m if merged_mask is None else cv2.bitwise_or(merged_mask, m)
    if merged_mask is None:
        return template_bgr

    # Clean mask
    kernel = np.ones((3, 3), np.uint8)
    merged_mask = cv2.morphologyEx(merged_mask, cv2.MORPH_OPEN, kernel, iterations=1)
    merged_mask = cv2.morphologyEx(merged_mask, cv2.MORPH_CLOSE, kernel, iterations=1)

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(merged_mask, connectivity=8)
    if num_labels <= 1:
        # Fallback for connected mega-component templates:
        h, w = template_bgr.shape[:2]
        if w >= int(h * 1.8):
            side = int(min(h * 0.95, w * 0.42))
            side = max(side, 12)
            x1, y1 = 0, 0
            x2 = min(w, x1 + side)
            y2 = min(h, y1 + side)
            cropped = template_bgr[y1:y2, x1:x2]
            return cropped if cropped.size else template_bgr
        return template_bgr

    # Pick largest connected purple component (excluding background 0)
    best_idx = 1
    best_area = 0
    for i in range(1, num_labels):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area > best_area:
            best_area = area
            best_idx = i

    x = int(stats[best_idx, cv2.CC_STAT_LEFT])
    y = int(stats[best_idx, cv2.CC_STAT_TOP])
    w = int(stats[best_idx, cv2.CC_STAT_WIDTH])
    h = int(stats[best_idx, cv2.CC_STAT_HEIGHT])
    if w < 8 or h < 8:
        return template_bgr

    pad = 3
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(template_bgr.shape[1], x + w + pad)
    y2 = min(template_bgr.shape[0], y + h + pad)
    cropped = template_bgr[y1:y2, x1:x2]
    if cropped.size == 0:
        return template_bgr

    # If still too wide, it's likely icon+bar connected; keep left square-ish part.
    ch, cw = cropped.shape[:2]
    if cw >= int(ch * 1.8):
        side = int(min(ch * 1.05, cw * 0.42))
        side = max(side, 12)
        x2s = min(cw, side)
        y2s = min(ch, side)
        sq = cropped[0:y2s, 0:x2s]
        if sq.size:
            return sq
    return cropped


def detect_purple_icon(image_path: Path, icon_cfg: Dict) -> Tuple[bool, float, float, str]:
    img = cv2.imread(str(image_path))
    if img is None:
        return False, 0.0, 0.0, "icon-image-read-failed"

    if not bool(icon_cfg.get("use_template", True)):
        ok, score, ratio, reason, _ = detect_purple_icon_blob_in_frame(img, icon_cfg)
        return ok, score, ratio, reason

    template_path = Path(icon_cfg.get("template_path", ""))
    if not template_path.exists():
        return False, 0.0, 0.0, f"icon-template-missing:{template_path}"
    tmpl = read_image(template_path)
    if tmpl is None:
        return False, 0.0, 0.0, "icon-template-read-failed"

    ok, score, ratio, reason, _bbox = _detect_purple_icon_from_frame_template(img, icon_cfg, tmpl)
    return ok, score, ratio, reason


def detect_purple_icon_in_frame(frame_bgr: np.ndarray, icon_cfg: Dict, template_bgr: np.ndarray) -> Tuple[bool, float, float, str]:
    if not bool(icon_cfg.get("use_template", True)):
        ok, score, ratio, reason, _ = detect_purple_icon_blob_in_frame(frame_bgr, icon_cfg)
        return ok, score, ratio, reason
    ok, score, ratio, reason, _bbox = _detect_purple_icon_from_frame_template(
        frame_bgr, icon_cfg, template_bgr
    )
    return ok, score, ratio, reason


def detect_purple_icon_in_frame_with_bbox(
    frame_bgr: np.ndarray, icon_cfg: Dict, template_bgr: np.ndarray
) -> Tuple[bool, float, float, str, Tuple[int, int, int, int]]:
    if not bool(icon_cfg.get("use_template", True)):
        return detect_purple_icon_blob_in_frame(frame_bgr, icon_cfg)
    return _detect_purple_icon_from_frame_template(frame_bgr, icon_cfg, template_bgr)


def detect_purple_icon_blob_in_frame(
    frame_bgr: np.ndarray, icon_cfg: Dict
) -> Tuple[bool, float, float, str, Tuple[int, int, int, int]]:
    if frame_bgr is None or frame_bgr.size == 0:
        return False, 0.0, 0.0, "icon-empty-frame", (0, 0, 0, 0)

    src_h, src_w = frame_bgr.shape[:2]
    scale = float(icon_cfg.get("blob_process_scale", 0.6))
    max_w = int(icon_cfg.get("blob_max_width", 1280))
    if src_w > 0 and max_w > 0:
        scale = min(scale, float(max_w) / float(src_w))
    scale = max(min(scale, 1.0), 0.25)

    work = frame_bgr
    if scale < 0.999:
        work = cv2.resize(frame_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    hsv_ranges = icon_cfg.get("hsv_ranges", [])
    hsv = cv2.cvtColor(work, cv2.COLOR_BGR2HSV)
    mask = _purple_mask_from_hsv(hsv, hsv_ranges)
    if mask is None:
        return False, 0.0, 0.0, "icon-hsv-range-invalid", (0, 0, 0, 0)

    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

    min_area = float(icon_cfg.get("purple_blob_min_area", 220))
    max_area = float(icon_cfg.get("purple_blob_max_area", 18000))
    min_fill = float(icon_cfg.get("purple_blob_min_fill", 0.22))
    purple_th = float(icon_cfg.get("purple_ratio_threshold", 0.12))

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    best = None
    best_score = -1.0
    for i in range(1, num_labels):
        area = float(stats[i, cv2.CC_STAT_AREA])
        x = int(stats[i, cv2.CC_STAT_LEFT])
        y = int(stats[i, cv2.CC_STAT_TOP])
        w = int(stats[i, cv2.CC_STAT_WIDTH])
        h = int(stats[i, cv2.CC_STAT_HEIGHT])
        if w <= 0 or h <= 0:
            continue
        if area < min_area or area > max_area:
            continue
        fill = area / float(w * h)
        if fill < min_fill:
            continue

        aspect = float(w) / float(max(h, 1))
        if aspect < 0.45 or aspect > 2.1:
            continue

        roi = work[y:y + h, x:x + w]
        purple_ratio = _purple_ratio(roi, hsv_ranges)
        if purple_ratio < purple_th:
            continue

        aspect_penalty = min(abs(np.log(max(aspect, 1e-6))), 1.0)
        aspect_score = 1.0 - aspect_penalty
        area_score = min(area / max(min_area, 1.0), 1.0)
        score = 0.55 * purple_ratio + 0.25 * fill + 0.12 * area_score + 0.08 * aspect_score
        if score > best_score:
            best_score = score
            best = (x, y, w, h, purple_ratio, fill, aspect, area)

    if best is None:
        global_ratio = float(np.count_nonzero(mask)) / float(mask.size) if mask.size else 0.0
        return False, 0.0, global_ratio, f"blob-miss(global_purple={global_ratio:.3f})", (0, 0, 0, 0)

    x, y, w, h, purple_ratio, fill, aspect, area = best
    if scale < 0.999:
        inv = 1.0 / scale
        x = int(round(x * inv))
        y = int(round(y * inv))
        w = int(round(w * inv))
        h = int(round(h * inv))
        x = max(0, min(x, src_w - 1))
        y = max(0, min(y, src_h - 1))
        w = max(1, min(w, src_w - x))
        h = max(1, min(h, src_h - y))
    reason = (
        f"blob(score={best_score:.3f},purple={purple_ratio:.3f},area={int(area)},"
        f"fill={fill:.3f},asp={aspect:.2f},scale={scale:.2f})"
    )
    return True, float(best_score), float(purple_ratio), reason, (x, y, w, h)


def append_report(row: ParseResult):
    with REPORT_PATH.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                time.strftime("%Y-%m-%d %H:%M:%S"),
                row.matched_file,
                row.pollution,
                row.reason,
                f"{row.icon_score:.4f}",
                f"{row.purple_ratio:.4f}",
                row.ocr_text,
            ]
        )


def process_one(engine, cfg: Dict, state: Dict, image_path: Path) -> Optional[ParseResult]:
    if not image_path.is_file():
        return None
    sha = image_sha1(image_path)
    if sha in state.get("processed_hashes", {}):
        return None

    pollution = 0
    reason = "no-match"
    ocr_text = ""
    icon_score = 0.0
    purple_ratio = 0.0

    icon_cfg = cfg.get("icon_mode", {})
    if icon_cfg.get("enabled", True):
        hit, icon_score, purple_ratio, icon_reason = detect_purple_icon(image_path, icon_cfg)
        if hit:
            pollution = int(icon_cfg.get("icon_pollution_value", 1))
            reason = f"icon-hit:{icon_reason}"
        else:
            reason = f"icon-miss:{icon_reason}"

    if pollution == 0:
        ocr_cfg = cfg.get("ocr_mode", {})
        if ocr_cfg.get("enabled", False):
            ocr_text = run_ocr(engine, image_path)
            pollution, ocr_reason = extract_pollution_from_text(ocr_text, ocr_cfg)
            reason = ocr_reason if pollution > 0 else f"{reason}|{ocr_reason}"

    state.setdefault("processed_hashes", {})[sha] = str(image_path)
    state.setdefault("records", []).append(
        {
            "time": int(time.time()),
            "file": str(image_path),
            "pollution": pollution,
            "reason": reason,
            "icon_score": icon_score,
            "purple_ratio": purple_ratio,
            "ocr_text": ocr_text,
        }
    )
    state["total_pollution"] = int(state.get("total_pollution", 0)) + pollution

    return ParseResult(
        pollution=pollution,
        reason=reason,
        ocr_text=ocr_text.replace("\n", " | ")[:300],
        matched_file=str(image_path),
        icon_score=icon_score,
        purple_ratio=purple_ratio,
    )


def list_images(watch_dir: Path, cfg: Dict) -> List[Path]:
    exts = {e.lower() for e in cfg.get("image_exts", [".png", ".jpg", ".jpeg"])}
    items = [p for p in watch_dir.glob("*") if p.is_file() and p.suffix.lower() in exts]
    items.sort(key=lambda p: p.stat().st_mtime)
    return items


def process_batch(engine, cfg: Dict, state: Dict, watch_dir: Path) -> int:
    count = 0
    for img in list_images(watch_dir, cfg):
        r = process_one(engine, cfg, state, img)
        if r is None:
            continue
        append_report(r)
        count += 1
        print(
            f"[OK] +{r.pollution} ({r.reason}) | score={r.icon_score:.3f} "
            f"| purple={r.purple_ratio:.3f} | total={state['total_pollution']} | {img.name}"
        )
    return count


def command_status(state: Dict):
    print(f"总污染: {state.get('total_pollution', 0)}")
    print(f"已处理截图: {len(state.get('processed_hashes', {}))}")
    print(f"记录数: {len(state.get('records', []))}")
    print(f"报表: {REPORT_PATH}")


def command_reset():
    save_json(STATE_PATH, {"total_pollution": 0, "processed_hashes": {}, "records": [], "pet_pool": {}})
    with REPORT_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "file", "pollution", "reason", "icon_score", "purple_ratio", "ocr_text"])
    print("已重置 state.json 和 report.csv")


def require_ocr_engine(cfg: Dict):
    ocr_enabled = cfg.get("ocr_mode", {}).get("enabled", False)
    if not ocr_enabled:
        return None
    if RapidOCR is None:
        print("OCR 模式开启但缺少依赖: rapidocr-onnxruntime")
        print("请运行: python -m pip install -r requirements.txt")
        sys.exit(1)
    return RapidOCR()


def _find_window_rect(title_contains: str):
    if gw is None:
        return None
    raw_target = (title_contains or "").strip()
    candidates = []
    if raw_target and raw_target not in {"????", "？", "?"}:
        candidates.append(raw_target.lower())
    for fallback in ["洛克王国：世界", "洛克王国"]:
        lowered = fallback.lower()
        if lowered not in candidates:
            candidates.append(lowered)
    if not candidates:
        return None
    for w in gw.getAllWindows():
        try:
            title = (w.title or "").lower()
            if w.width <= 50 or w.height <= 50:
                continue
            if any(target in title for target in candidates):
                return {"left": int(w.left), "top": int(w.top), "width": int(w.width), "height": int(w.height)}
        except Exception:
            continue
    return None


def require_screen_tools():
    if mss is None:
        print("缺少实时屏幕依赖: mss")
        print("请运行: python -m pip install -r requirements.txt")
        sys.exit(1)


def run_screen_watch(cfg: Dict, state: Dict):
    require_screen_tools()

    icon_cfg = cfg.get("icon_mode", {})
    template_path = Path(icon_cfg.get("template_path", ""))
    if not template_path.exists():
        print(f"模板图不存在: {template_path}")
        print("请先放置污染图标模板图后再运行。")
        return
        template = read_image(template_path)
    if template is None:
        print(f"模板图读取失败: {template_path}")
        return

    screen_cfg = cfg.get("screen_mode", {})
    interval = float(screen_cfg.get("capture_interval_sec", 0.35))
    present_need = int(screen_cfg.get("present_confirm_frames", 2))
    absent_need = int(screen_cfg.get("absent_confirm_frames", 2))
    min_gap = float(screen_cfg.get("min_trigger_gap_sec", 1.2))
    icon_value = int(icon_cfg.get("icon_pollution_value", 1))

    monitor_index = int(screen_cfg.get("monitor_index", 1))
    window_hint = str(screen_cfg.get("window_title_contains", "") or "")

    present_count = 0
    absent_count = 0
    active = False
    last_trigger_ts = 0.0
    last_info_ts = 0.0

    print("开始实时屏幕识别（紫色污染图标）")
    print("按 Ctrl+C 停止")

    with mss.mss() as sct:
        monitors = sct.monitors
        if monitor_index < 1 or monitor_index >= len(monitors):
            monitor_index = 1

        try:
            while True:
                region = _find_window_rect(window_hint)
                monitor = region if region else monitors[monitor_index]
                frame = np.array(sct.grab(monitor))
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

                hit, score, ratio, reason = detect_purple_icon_in_frame(frame_bgr, icon_cfg, template)
                now = time.time()

                if hit:
                    present_count += 1
                    absent_count = 0
                else:
                    absent_count += 1
                    present_count = 0

                stable_present = present_count >= present_need
                stable_absent = absent_count >= absent_need

                if stable_present and (not active) and (now - last_trigger_ts >= min_gap):
                    active = True
                    last_trigger_ts = now
                    state["total_pollution"] = int(state.get("total_pollution", 0)) + icon_value
                    rec = {
                        "time": int(now),
                        "file": "<SCREEN>",
                        "pollution": icon_value,
                        "reason": f"screen-hit:{reason}",
                        "icon_score": score,
                        "purple_ratio": ratio,
                        "ocr_text": "",
                    }
                    state.setdefault("records", []).append(rec)
                    tracker_row = ParseResult(
                        pollution=icon_value,
                        reason=f"screen-hit:{reason}",
                        ocr_text="",
                        matched_file="<SCREEN>",
                        icon_score=score,
                        purple_ratio=ratio,
                    )
                    append_report(tracker_row)
                    save_json(STATE_PATH, state)
                    print(
                        f"[TRIGGER] +{icon_value} | total={state['total_pollution']} "
                        f"| score={score:.3f} purple={ratio:.3f}"
                    )

                if stable_absent and active:
                    active = False

                if now - last_info_ts >= 2.0:
                    print(
                        f"[LIVE] hit={hit} active={active} score={score:.3f} purple={ratio:.3f} "
                        f"| total={state.get('total_pollution', 0)}"
                    )
                    last_info_ts = now

                time.sleep(interval)
        except KeyboardInterrupt:
            save_json(STATE_PATH, state)
            print("\n已停止实时识别并保存状态")


def main():
    parser = argparse.ArgumentParser(description="洛克王国污染自动统计（图标紫色优先）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="初始化配置与状态文件")
    sub.add_parser("status", help="查看当前统计状态")
    sub.add_parser("reset", help="清空统计状态与报表")

    p_once = sub.add_parser("once", help="扫描一次截图目录")
    p_once.add_argument("--dir", default=None, help="覆盖配置里的截图目录")

    p_watch = sub.add_parser("watch", help="持续监听截图目录")
    p_watch.add_argument("--dir", default=None, help="覆盖配置里的截图目录")
    sub.add_parser("screen-watch", help="实时屏幕识别模式（无需截图）")

    args = parser.parse_args()
    init_files()

    if args.cmd == "init":
        print("初始化完成:")
        print(f"- {CONFIG_PATH}")
        print(f"- {STATE_PATH}")
        print(f"- {REPORT_PATH}")
        print(f"- 模板图请放: {ICON_TEMPLATE}")
        return

    if args.cmd == "reset":
        command_reset()
        return

    cfg = load_json(CONFIG_PATH, default_config())
    cfg = merge_defaults(cfg, default_config())
    state = load_json(STATE_PATH, {"total_pollution": 0, "processed_hashes": {}, "records": []})

    if args.cmd == "status":
        command_status(state)
        return

    if args.cmd == "screen-watch":
        run_screen_watch(cfg, state)
        return

    watch_dir = Path(args.dir if args.dir else cfg.get("watch_dir", "."))
    if not watch_dir.exists():
        print(f"截图目录不存在: {watch_dir}")
        print("请修改 config.json 的 watch_dir，或使用 --dir")
        return

    engine = require_ocr_engine(cfg)

    if args.cmd == "once":
        c = process_batch(engine, cfg, state, watch_dir)
        save_json(STATE_PATH, state)
        print(f"本次处理: {c} 张")
        command_status(state)
        return

    if args.cmd == "watch":
        interval = float(cfg.get("poll_interval_sec", 2))
        print(f"开始监听: {watch_dir} (每 {interval}s 扫描一次)")
        print("按 Ctrl+C 停止")
        try:
            while True:
                c = process_batch(engine, cfg, state, watch_dir)
                if c:
                    save_json(STATE_PATH, state)
                time.sleep(interval)
        except KeyboardInterrupt:
            save_json(STATE_PATH, state)
            print("\n已停止监听并保存状态")


if __name__ == "__main__":
    main()
