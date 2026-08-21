

def format_documents_to_search_results(documents: dict) -> list[dict] | None:
    if documents is None:
        return []

    hits = documents.get("hits", [])
    return [
        {
            "conversation_id": hit["conversation_id"],
            "score": hit["_rankingScore"],
        }
        for hit in hits
    ]

def format_search_results_to_conversation_ids_and_scores(search_results: list[dict[str, any]]) -> tuple[list[str], list[float]]:
    return ([result["conversation_id"] for result in search_results], 
            [round(result["score"], 3) for result in search_results])