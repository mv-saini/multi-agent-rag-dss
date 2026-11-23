from urllib.parse import quote, urlencode

from core.storage import evidence_store
from utils import helpers


def bundle_ids(values: dict) -> list[str]:
    ids = [
        message.additional_kwargs.get("evidence_bundle_id")
        for message in values.get("messages", [])
    ]
    ids.append(values.get("evidence_bundle_id"))
    return list(dict.fromkeys(bundle_id for bundle_id in ids if bundle_id))


def display_bundle(bundle_id: str, thread_id: str) -> dict:
    bundle = evidence_store.load(bundle_id, thread_id)
    context = bundle["context"]
    return {
        "id": bundle_id,
        "retrieved_context": {
            "web_results": helpers.format_web_results(context.get("web_results", [])),
            "vector_docs": helpers.format_vector_docs(context.get("vector_docs", [])),
            "spatial_analysis": helpers.format_spatial_analysis(
                context.get("spatial_analysis", [])
            ),
        },
        "map_layers": [
            {
                **{key: value for key, value in layer.items() if not key.startswith("_export_")},
                "download_url": (
                    f"/api/threads/{quote(thread_id, safe='')}/evidence/{quote(bundle_id, safe='')}/shapefile?"
                    + urlencode({"layer_id": layer["layer_id"]})
                ),
            }
            for layer in bundle["map_layers"]
        ],
        "citation_sources": bundle["citation_sources"],
        "web_results": context.get("web_results", []),
    }
