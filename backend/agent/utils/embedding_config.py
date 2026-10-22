"""One resolved embedding binding shared by few-shot reads and feedback writes.

Defaults are for new installs. Pin the original model and size for existing
collections; changing a profile never authorizes a migration or re-embedding.
"""
from agent.utils.model_profiles import load_profile, EMBEDDING_DIMENSIONS, ModelConfigurationError

_binding = load_profile()["embeddings"]["fewshot"]
FEWSHOT_EMBEDDING_MODEL = _binding["model"]
FEWSHOT_EMBEDDING_SIZE = _binding["dimensions"]


def verify_vector_size(current, expected, collection):
    if type(current) is not int or current != expected:
        raise ModelConfigurationError(
            f"Collection {collection} is incompatible with configured {expected}-dimension embeddings. "
            "Preserve its original model/dimension binding; no automatic rebuild is performed."
        )


def describe():
    return f"{FEWSHOT_EMBEDDING_MODEL} ({FEWSHOT_EMBEDDING_SIZE}-d)"
