from pathlib import Path
from uuid import uuid4
import pytest
from proofpay.extraction.stub import OfflineStubExtractor
from proofpay.extraction.preprocess import preprocess_image

def test_offline_extractor():
    man_path = Path(__file__).parents[2] / 'fixtures' / 'demo' / 'manifest.json'
    img_path = Path(__file__).parents[2] / 'fixtures' / 'demo' / 'images' / 'G01.jpg'
    
    ext = OfflineStubExtractor(man_path)
    
    img_bytes = img_path.read_bytes()
    claim = ext.extract(img_bytes, claim_id="test-1234")
    
    assert claim.claim_id == "test-1234"
    assert claim.amount.minor == 150000
    assert claim.provider == "easypaisa"
    assert claim.sender_name == "Bilal Ahmed Khan"
    assert claim.reference_id == "EP0000011"
    assert claim.occurred_at is not None

def test_preprocess_image_no_op_on_small():
    # Make small dummy image
    from PIL import Image
    import io
    
    img = Image.new('RGB', (800, 800), color = 'red')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    img_bytes = buf.getvalue()
    
    res = preprocess_image(img_bytes, max_long_edge=1024)
    assert res == img_bytes

def test_preprocess_image_downscales():
    from PIL import Image
    import io
    
    img = Image.new('RGB', (2000, 1000), color = 'red')
    buf = io.BytesIO()
    img.save(buf, format='JPEG')
    img_bytes = buf.getvalue()
    
    res = preprocess_image(img_bytes, max_long_edge=1024)
    
    # Verify new dim
    img_out = Image.open(io.BytesIO(res))
    assert img_out.width == 1024
    assert img_out.height == 512
