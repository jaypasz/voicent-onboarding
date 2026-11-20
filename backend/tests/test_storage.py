"""The storage client's own calls, against a fake Supabase. No network."""
import httpx

from app.config import Settings
from app.storage import Storage, stored_content_type


def _storage(handler):
    s = Settings(database_url="sqlite://", supabase_url="https://sb.test", supabase_service_key="svc")
    return Storage(s, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_head_asks_for_a_range_and_stops_at_n_bytes_even_if_the_range_is_ignored():
    seen = {}

    def handler(req):
        seen["range"], seen["path"] = req.headers.get("range"), req.url.path
        return httpx.Response(200, content=b"x" * 100_000)  # a server that sends the whole file anyway

    st = _storage(handler)
    out = st.head("org/ob/step/abc-logo.png", 16)
    assert out == b"x" * 16
    assert seen["range"] == "bytes=0-15"
    assert seen["path"].startswith("/storage/v1/object/authenticated/")


def test_head_is_none_when_the_object_is_missing():
    assert _storage(lambda req: httpx.Response(404)).head("p", 16) is None


def test_stored_content_type_reads_the_shapes_supabase_uses():
    assert stored_content_type({"content_type": "image/png"}) == "image/png"
    assert stored_content_type({"metadata": {"mimetype": "Image/PNG; charset=binary"}}) == "image/png"
    assert stored_content_type({}) == ""
