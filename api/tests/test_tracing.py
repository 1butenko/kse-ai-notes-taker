from app.llm import usage_details


def test_usage_details_splits_inclusive_counts_into_exclusive_buckets() -> None:
    usage = {
        "prompt_tokens": 17903,
        "completion_tokens": 188,
        "total_tokens": 18091,
        "cost": 0.0021,
        "prompt_tokens_details": {"cached_tokens": 17817},
        "completion_tokens_details": {"reasoning_tokens": 40},
    }

    assert usage_details(usage) == {
        "input": 86,
        "input_cached_tokens": 17817,
        "output": 148,
        "output_reasoning_tokens": 40,
    }


def test_usage_details_without_details() -> None:
    usage = {"prompt_tokens": 10, "completion_tokens": 5, "prompt_tokens_details": None}

    assert usage_details(usage) == {"input": 10, "output": 5}
