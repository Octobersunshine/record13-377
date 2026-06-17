from flask import Flask, request, send_file, jsonify
from PIL import Image, ImageFilter, ImageEnhance, ImageOps
import io

app = Flask(__name__)

FILTERS = [
    "grayscale", "vintage", "blur", "sharpen",
    "emboss", "invert", "edge_enhance", "contour",
]


def apply_grayscale(img):
    return img.convert("L").convert("RGB")


def apply_vintage(img):
    img = img.convert("RGB")
    r, g, b = img.split()
    r = r.point(lambda x: min(255, x * 1.2))
    g = g.point(lambda x: min(255, x * 0.9))
    b = b.point(lambda x: min(255, x * 0.7))
    img = Image.merge("RGB", (r, g, b))
    img = ImageEnhance.Contrast(img).enhance(0.9)
    img = ImageEnhance.Brightness(img).enhance(1.1)
    return img


def apply_blur(img):
    return img.filter(ImageFilter.GaussianBlur(radius=3))


def apply_sharpen(img):
    return img.filter(ImageFilter.SHARPEN)


def apply_emboss(img):
    return img.filter(ImageFilter.EMBOSS)


def apply_invert(img):
    return ImageOps.invert(img.convert("RGB"))


def apply_edge_enhance(img):
    return img.filter(ImageFilter.EDGE_ENHANCE_MORE)


def apply_contour(img):
    return img.filter(ImageFilter.CONTOUR)


FILTER_MAP = {
    "grayscale": apply_grayscale,
    "vintage": apply_vintage,
    "blur": apply_blur,
    "sharpen": apply_sharpen,
    "emboss": apply_emboss,
    "invert": apply_invert,
    "edge_enhance": apply_edge_enhance,
    "contour": apply_contour,
}


@app.route("/")
def index():
    return jsonify({
        "service": "Image Filter Service",
        "version": "1.0.0",
        "available_filters": FILTERS,
        "usage": "POST /filter/<filter_name> with multipart form field 'image'",
    })


@app.route("/filters", methods=["GET"])
def list_filters():
    return jsonify({"filters": FILTERS})


@app.route("/filter/<filter_name>", methods=["POST"])
def apply_filter(filter_name):
    if filter_name not in FILTER_MAP:
        return jsonify({"error": f"Unknown filter '{filter_name}'", "available_filters": FILTERS}), 400

    if "image" not in request.files:
        return jsonify({"error": "No image provided. Use form field 'image'."}), 400

    file = request.files["image"]
    try:
        img = Image.open(file.stream)
    except Exception:
        return jsonify({"error": "Invalid image file."}), 400

    try:
        result = FILTER_MAP[filter_name](img)
    except Exception as e:
        return jsonify({"error": f"Filter application failed: {str(e)}"}), 500

    buf = io.BytesIO()
    fmt = img.format or "PNG"
    save_fmt = fmt if fmt in ("JPEG", "PNG", "BMP", "GIF", "WEBP") else "PNG"
    if save_fmt == "JPEG" and result.mode in ("RGBA", "LA", "P"):
        result = result.convert("RGB")
    result.save(buf, format=save_fmt)
    buf.seek(0)

    mime = {"JPEG": "image/jpeg", "PNG": "image/png", "BMP": "image/bmp", "GIF": "image/gif", "WEBP": "image/webp"}
    return send_file(buf, mimetype=mime.get(save_fmt, "image/png"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
