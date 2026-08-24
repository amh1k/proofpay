import io
from PIL import Image

def preprocess_image(image_bytes: bytes, max_long_edge: int = 1024) -> bytes:
    """Downscale image to max_long_edge before any model call to save tokens.
    
    Qwen-VL and other vision models charge by pixel (token blocks).
    A 1080x2340 image uses ~2.5M pixels. Downscaling to 1024px on the long edge
    significantly drops the token cost while preserving OCR readability.
    """
    img = Image.open(io.BytesIO(image_bytes))
    
    # Calculate new dimensions
    longest = max(img.width, img.height)
    if longest <= max_long_edge:
        return image_bytes  # Already small enough
        
    scale = max_long_edge / longest
    new_w = int(img.width * scale)
    new_h = int(img.height * scale)
    
    # LANCZOS is high quality for text
    resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    
    buf = io.BytesIO()
    # Save as JPEG to match mobile delivery and save space
    resized.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue()
