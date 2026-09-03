from proofpay.config import Settings
from proofpay.extraction.dashscope_ocr import DEFAULT_MODEL


def test_qwen_without_key_falls_back_to_deterministic():
    """A missing credential degrades quality; it must not break the pipeline."""
    settings = Settings(receipt_extractor="qwen", dashscope_api_key=None)

    assert settings.effective_receipt_extractor() == "deterministic"


def test_qwen_with_key_is_used():
    settings = Settings(receipt_extractor="qwen", dashscope_api_key="sk-test")

    assert settings.effective_receipt_extractor() == "qwen"


def test_qwen_model_defaults_to_the_adapter_pin_rather_than_a_second_name():
    """`None` means "whatever the adapter pins", and that is deliberate.

    This setting used to read `"qwen-vl-max"` and was never passed to anything,
    so the adapter's own `DEFAULT_MODEL` ran regardless. Two model names in the
    tree, one dead, and the live one was not the one you would find by reading
    the config. If someone reintroduces a literal here, they have reintroduced
    the same trap.
    """
    assert Settings().qwen_model is None


def test_the_configured_model_actually_reaches_the_cloud_adapter():
    """The knob has to survive settings -> service -> factory -> adapter.

    Asserting on `Settings` alone would have passed happily for as long as the
    bug existed; the whole defect was that the value stopped at the settings
    object. So build the extractor the way the API does and read the model off
    the thing that will make the call.
    """
    from proofpay.extraction.service import build_extractor

    pinned = build_extractor(api_key="test-key", mode="cloud")
    assert pinned.model == DEFAULT_MODEL

    overridden = build_extractor(api_key="test-key", mode="cloud", model="qwen-vl-max")
    assert overridden.model == "qwen-vl-max"
