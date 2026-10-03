from app.services.identity_verify import verify_upload_identity


def test_identity_from_content_not_filename():
    # Filename lies; content has the id
    data = b"Title page\nDO-178C Software Considerations\nRev B\n"
    v = verify_upload_identity(
        data,
        filename="totally-wrong-name.txt",
        mime_type="text/plain",
        expected_doc_id="DO-178C",
    )
    assert v.ok is True


def test_identity_rejects_mismatch():
    data = b"This document is MIL-STD-498 only.\n"
    v = verify_upload_identity(
        data,
        filename="DO-178C.txt",
        mime_type="text/plain",
        expected_doc_id="DO-178C",
    )
    assert v.ok is False
