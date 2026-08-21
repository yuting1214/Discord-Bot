import json
from backend.fastapi.request_handler.api_requests import rollback_manager
from backend.discord.utils import extract_uuid, generate_uuid_key
from backend.discord.operations.async_ import llm_api_call_async
from backend.discord.operations.sync import (
    prepare_memory_for_llm,
    get_or_create_server,
    get_or_create_channel,
    get_or_create_user,
    manage_session,
    find_active_sessions,
    get_session_if_exists,
    activate_session,
    deactivate_session,
    create_conversation,
    update_conversation,
    create_message,
    get_messages_by_conversations,
    format_messages_to_search_results,
    create_command_log,
)

from backend.meilisearch.insert import insert_documents
from backend.meilisearch.search import hybrid_search
from backend.meilisearch.format import (
    format_documents_to_search_results,
   format_search_results_to_conversation_ids_and_scores
)

async def start_or_resume_session(
        server_discord_id: str,
        server_name: str,
        owner_discord_id: str,
        channel_discord_id: str,
        channel_name: str,
        user_discord_id: str,
        user_name: str,
        user_input: str,
        is_group: bool,
        is_new_session: bool
        ) -> dict:
    try:
        with rollback_manager() as resources_to_rollback:
            # Step 1: User Handling
            user_id = get_or_create_user(user_discord_id, user_name, resources_to_rollback)

            # Step 2: Server Handling
            server_id = get_or_create_server(server_discord_id, server_name, owner_discord_id, user_id, resources_to_rollback)

            # Step 3: Channel Handling
            channel_id = get_or_create_channel(server_id, channel_discord_id, channel_name, user_id, is_group, resources_to_rollback)

            # Step 4: Session Handling
            current_session = manage_session(channel_discord_id, user_id, is_group, is_new_session, resources_to_rollback)

            # Create a new conversation
            new_conversation = create_conversation(current_session["id"], resources_to_rollback)

            # Create a new message
            new_message = create_message(channel_discord_id, current_session["id"], new_conversation["id"], user_id, "user", user_input, resources_to_rollback)

            # Add the document in the search index
            document_data = [{
                "conversation_id": new_conversation["id"],
                "user_input": user_input,
                "session_id": current_session["id"]
            }]
            if is_group:
                insert_documents(channel_id, document_data)
            else:
                insert_documents(generate_uuid_key(user_id, channel_id), document_data)

            # Start a new command log
            new_command_log = create_command_log(user_id, current_session["id"], is_group, is_new_session, resources_to_rollback)

            return {
                'message': new_message
            }

    except Exception as e:
        return {
            "error": str(e),
            "message": None
        }
    
async def complete_session_chat(
        server_discord_id: str,
        server_name: str,
        owner_discord_id: str,
        channel_discord_id: str,
        channel_name: str,
        user_discord_id: str,
        user_name: str,
        user_input: str,
        is_group: bool,
        is_new_session: bool
        ) -> dict:
    try:
        # Using async context manager
        with rollback_manager() as resources_to_rollback:
            # the async function to ensure it completes before moving forward
            session_result = await start_or_resume_session(server_discord_id, server_name, owner_discord_id, channel_discord_id, channel_name, user_discord_id, user_name, user_input, is_group, is_new_session)

            # Check for errors in the session_result
            if "error" in session_result:
                return {"error": session_result["error"]} 

            # Extract necessary information from the result
            current_session_id = session_result['message']['session_id']
            current_conversation_id = session_result['message']['conversation_id']
            current_user_id = session_result['message']['user_id']

            # the async function to prepare memory
            memory = [] if is_new_session else prepare_memory_for_llm(current_session_id)
            
            # the async function to call LLM API
            llm_result = await llm_api_call_async(user_input, memory)

            # the async function to create a new message instance, retaining the
            # reasoning trace so the next turn can resume it
            new_message = create_message(
                channel_discord_id, current_session_id, current_conversation_id, current_user_id,
                "model", llm_result.text, resources_to_rollback,
                reasoning_details=llm_result.reasoning_details,
            )

            # the async function to update the conversation
            update_conversation(current_conversation_id, resources_to_rollback)

            return {
                "llm_response": llm_result.text
            }

    except Exception as e:
        return {"error": f"Failed to process LLM response: {str(e)}"}

async def resume_session(
        server_discord_id: str,
        server_name: str,
        owner_discord_id: str,
        channel_discord_id: str,
        channel_name: str,
        user_discord_id: str,
        user_name: str,
        user_input: str,
        is_group: bool
        ) -> dict:
    resume_session_id = extract_uuid(user_input)
    
    if resume_session_id:
        try:
            with rollback_manager() as resources_to_rollback:
                # Step 1: User Handling
                user_id = get_or_create_user(user_discord_id, user_name, resources_to_rollback)

                # Step 2: Server Handling
                server_id = get_or_create_server(server_discord_id, server_name, owner_discord_id, user_id, resources_to_rollback)

                # Step 3: Channel Handling
                channel_id = get_or_create_channel(server_id, channel_discord_id, channel_name, user_id, is_group, resources_to_rollback)
                
                # Step 4: Check for Active Session
                current_sessions = find_active_sessions(channel_discord_id, user_id, is_group)
                
                # Step 3: Resume the Specified Session
                resume_session = get_session_if_exists(resume_session_id)

                if resume_session:
                    activate_session(resume_session_id, resume_session, resources_to_rollback)
                    
                    # Step 4: Deactivate Current Session if Exists
                    if current_sessions:
                        current_session = current_sessions[0]
                        deactivate_session(current_session["id"], current_session, resources_to_rollback)
                    
                    return {
                        "message": f"Session - {resume_session_id} has resumed."
                    }
                else:
                    return {
                        "message": f"Session - {resume_session_id} does not exist!"
                    }
        except Exception as e:
            return {
                "error": str(e),
                "message": str(e)
            }
    else:
        return {
            "message": "Invalid UUID input."
        }

async def search_messages_and_list_sessions(
        server_discord_id: str,
        server_name: str,
        owner_discord_id: str,
        channel_discord_id: str,
        channel_name: str,
        user_discord_id: str,
        user_name: str,
        user_input: str,
        is_group: bool
        ) -> dict:
    try:
        with rollback_manager() as resources_to_rollback:
            # Step 1: User Handling
            user_id = get_or_create_user(user_discord_id, user_name, resources_to_rollback)
        
            # Step 2: Server Handling
            server_id = get_or_create_server(server_discord_id, server_name, owner_discord_id, user_id, resources_to_rollback)

            # Step 3: Channel Handling
            channel_id = get_or_create_channel(server_id, channel_discord_id, channel_name, user_id, is_group, resources_to_rollback)
            
            # Step 4: Search for Documents
            search_index = channel_id if is_group else generate_uuid_key(user_id, channel_id)
            documents = hybrid_search(search_index, user_input)
            conversation_results = format_documents_to_search_results(documents)
            conversation_ids, scores = format_search_results_to_conversation_ids_and_scores(conversation_results)

            # Step 5: Fetch Messages
            search_result_message = "No search results found."
            if conversation_ids:
                raw_messages = get_messages_by_conversations(conversation_ids)
                search_results = format_messages_to_search_results(raw_messages, scores)
                search_result_message = json.dumps(search_results, indent=4)
            
            return {
                "message": search_result_message
            }
    except Exception as e:
        return {
            "error": str(e),
            "message": str(e)
        }