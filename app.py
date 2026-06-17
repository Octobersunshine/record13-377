from flask import Flask, request, send_file, jsonify
from PIL import Image, ImageFilter, ImageEnhance, ImageOps
import io
import zipfile

app = Flask(__name__)

FILTERS = [
    "grayscale", "vintage", "blur", "sharpen",
    "emboss", "invert", "edge_enhance", "contour",
]


def _load_image(file_storage):
    img = Image.open(file_storage.stream)
    img.load()
    img = img.copy()
    return img


def _ensure_rgb(img):
    if img.mode in ("RGBA", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        return background
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _mix(img, filtered, intensity):
    alpha = max(0.0, min(1.0, intensity / 100.0))
    if alpha == 0.0:
        return img.copy()
    if alpha == 1.0:
        return filtered
    base = _ensure_rgb(img)
    filtered_rgb = _ensure_rgb(filtered)
    return Image.blend(base, filtered_rgb, alpha)


def _filter_grayscale(img):
    return img.convert("L").convert("RGB")


def _filter_vintage(img):
    img = _ensure_rgb(img)
    r, g, b = img.split()
    r = r.point(lambda x: min(255, x * 1.2))
    g = g.point(lambda x: min(255, x * 0.9))
    b = b.point(lambda x: min(255, x * 0.7))
    result = Image.merge("RGB", (r, g, b))
    result = ImageEnhance.Contrast(result).enhance(0.9)
    result = ImageEnhance.Brightness(result).enhance(1.1)
    return result


def _filter_blur(img):
    return img.filter(ImageFilter.GaussianBlur(radius=3))


def _filter_sharpen(img):
    return img.filter(ImageFilter.SHARPEN)


def _filter_emboss(img):
    return img.filter(ImageFilter.EMBOSS)


def _filter_invert(img):
    return ImageOps.invert(_ensure_rgb(img))


def _filter_edge_enhance(img):
    return img.filter(ImageFilter.EDGE_ENHANCE_MORE)


def _filter_contour(img):
    return img.filter(ImageFilter.CONTOUR)


FILTER_RAW = {
    "grayscale": _filter_grayscale,
    "vintage": _filter_vintage,
    "blur": _filter_blur,
    "sharpen": _filter_sharpen,
    "emboss": _filter_emboss,
    "invert": _filter_invert,
    "edge_enhance": _filter_edge_enhance,
    "contour": _filter_contour,
}


def apply_filter(img, filter_name, intensity=100):
    if not (0 <= intensity <= 100):
        raise ValueError("intensity must be between 0 and 100")
    filtered = FILTER_RAW[filter_name](img.copy())
    return _mix(img, filtered, intensity)


def _parse_intensity(val, default=100):
    try:
        i = int(val)
    except (TypeError, ValueError):
        return None, "intensity must be an integer"
    if not (0 <= i <= 100):
        return None, "intensity must be between 0 and 100"
    return i, None


def _save_image(img, source_format):
    buf = io.BytesIO()
    save_fmt = source_format if source_format in ("JPEG", "PNG", "BMP", "GIF", "WEBP") else "PNG"
    out = img
    if save_fmt == "JPEG" and out.mode in ("RGBA", "LA", "P"):
        out = out.convert("RGB")
    out.save(buf, format=save_fmt)
    buf.seek(0)
    return buf, save_fmt


@app.route("/")
def index():
    return jsonify({
        "service": "Image Filter Service",
        "version": "2.0.0",
        "available_filters": FILTERS,
        "usage": {
            "single": "POST /filter/<filter_name> with multipart form field 'image', optional 'intensity' (0-100, default 100)",
            "batch": "POST /batch with form fields 'image' and 'filters' (comma-separated, optionally filter:intensity per entry). Each filter applied independently to the original.",
            "combine": "POST /combine with form fields 'image' and 'filters' (comma-separated, optionally filter:intensity per entry). Filters applied sequentially in given order (combined).",
        },
    })


@app.route("/filters", methods=["GET"])
def list_filters():
    return jsonify({"filters": FILTERS})


@app.route("/filter/<filter_name>", methods=["POST"])
def single_filter(filter_name):
    if filter_name not in FILTER_RAW:
        return jsonify({"error": f"Unknown filter '{filter_name}'", "available_filters": FILTERS}), 400

    if "image" not in request.files:
        return jsonify({"error": "No image provided. Use form field 'image'."}), 400

    intensity, err = _parse_intensity(request.form.get("intensity", request.args.get("intensity", 100)))
    if err:
        return jsonify({"error": err}), 400

    file = request.files["image"]
    try:
        img = _load_image(file)
    except Exception:
        return jsonify({"error": "Invalid image file."}), 400

    try:
        result = apply_filter(img, filter_name, intensity)
    except Exception as e:
        return jsonify({"error": f"Filter application failed: {str(e)}"}), 500

    buf, save_fmt = _save_image(result, img.format or "PNG")
    mime = {"JPEG": "image/jpeg", "PNG": "image/png", "BMP": "image/bmp", "GIF": "image/gif", "WEBP": "image/webp"}
    return send_file(buf, mimetype=mime.get(save_fmt, "image/png"))


def _parse_filter_chain(spec):
    items = [s.strip() for s in spec.split(",") if s.strip()]
    chain = []
    for item in items:
        if ":" in item:
            name, val = item.rsplit(":", 1)
            name = name.strip()
            intensity, err = _parse_intensity(val.strip())
            if err:
                return None, f"Invalid filter spec '{item}': {err}"
        else:
            name = item
            intensity = 100
        if name not in FILTER_RAW:
            return None, f"Unknown filter '{name}'"
        chain.append((name, intensity))
    if not chain:
        return None, "No valid filters specified"
    return chain, None


@app.route("/batch", methods=["POST"])
def batch_filter():
    if "image" not in request.files:
        return jsonify({"error": "No image provided. Use form field 'image'."}), 400

    spec = request.form.get("filters", "")
    if not spec:
        return jsonify({"error": "No filters specified. Use form field 'filters' (comma-separated, e.g. 'grayscale:50,blur:80')."}), 400

    chain, err = _parse_filter_chain(spec)
    if err:
        return jsonify({"error": err, "available_filters": FILTERS}), 400

    file = request.files["image"]
    try:
        img = _load_image(file)
    except Exception:
        return jsonify({"error": "Invalid image file."}), 400

    save_fmt = img.format or "PNG"
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, intensity in chain:
            try:
                result = apply_filter(img, name, intensity)
                img_buf, _ = _save_image(result, save_fmt)
                fname = f"{name}_{intensity}.{save_fmt.lower()}"
                zf.writestr(fname, img_buf.read())
            except Exception as e:
                return jsonify({"error": f"Filter '{name}' failed: {str(e)}"}), 500

    zip_buf.seek(0)
    return send_file(zip_buf, mimetype="application/zip", as_attachment=True, download_name="filters.zip")


@app.route("/combine", methods=["POST"])
def combine_filters():
    if "image" not in request.files:
        return jsonify({"error": "No image provided. Use form field 'image'."}), 400

    spec = request.form.get("filters", "")
    if not spec:
        return jsonify({"error": "No filters specified. Use form field 'filters' (comma-separated, e.g. 'grayscale:100,blur:70'). Filters applied left-to-right."}), 400

    chain, err = _parse_filter_chain(spec)
    if err:
        return jsonify({"error": err, "available_filters": FILTERS}), 400

    file = request.files["image"]
    try:
        img = _load_image(file)
    except Exception:
        return jsonify({"error": "Invalid image file."}), 400

    try:
        current = img
        for name, intensity in chain:
            current = apply_filter(current, name, intensity)
    except Exception as e:
        return jsonify({"error": f"Filter chain failed at '{name}': {str(e)}"}), 500

    buf, save_fmt = _save_image(current, img.format or "PNG")
    mime = {"JPEG": "image/jpeg", "PNG": "image/png", "BMP": "image/bmp", "GIF": "image/gif", "WEBP": "image/webp"}
    return send_file(buf, mimetype=mime.get(save_fmt, "image/png"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
