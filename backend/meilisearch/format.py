from typing import Optional, List, Dict, Tuple

def format_documents_to_search_results(documents: dict) -> Optional[List[dict]]:
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

def format_search_results_to_conversation_ids_and_scores(search_results: List[Dict[str, any]]) -> Tuple[List[str], List[float]]:
    return ([result["conversation_id"] for result in search_results], 
            [round(result["score"], 3) for result in search_results])