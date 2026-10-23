import time
import json
from datetime import datetime, timedelta
import pymysql
from uuid import uuid4
from session.services.logger import logger
from typing import List, Dict, Optional
from sqlmodel import select
from models.sql_models import ChatbotInvitations, ChatbotDetails, ChatSessions, ChatLogs
from session.services.sqlmodel_session import get_async_session
from sqlalchemy import func
from sqlalchemy.engine.row import Row
from session.utils.common import get_user_id_from_email

async def log_new_session(user_id, chatbot_id, user_query):
	try:
		session_id = str(uuid4())
		session_title = user_query[:25] + '...' if len(user_query) > 25 else user_query
		display_message = user_query
		async with get_async_session() as session:
			obj = ChatSessions(
				session_id=session_id,
				chatbot_id=chatbot_id,
				agent_id=chatbot_id,  # Sync both IDs for consistency
				user_id=user_id,
				session_title=session_title,
				display_message=display_message
			)
			session.add(obj)
			await session.commit()
			created_time = obj.created_time
			logger.info(f"New session created: {session_id} at {created_time}")
			return {
				"session_id": session_id,
				"created_time": created_time.isoformat() + "Z" if created_time else None,
				"display_message": display_message,
				"session_title": session_title
			}
	except Exception as e:
		logger.error(f"Error logging new session: {e}")
		raise

async def get_past_conversation(session_id):
	try:
		start_time = time.time()
		messages = []
		async with get_async_session() as session:
			res = await session.execute(
				select(ChatLogs).where(ChatLogs.session_id == session_id).order_by(ChatLogs.created_at)
			)
			for row in res.all():
				message_user = {"role": "user", "content": row.user_query}
				message_assistant = {"role": "assistant", "content": row.gpt_response}
				messages.extend([message_user, message_assistant])
		elapsed_time = time.time() - start_time
		logger.info(f"History For Context(get_conversation):{messages}, elapsed_time: {elapsed_time}")
		return messages
	except Exception as e:
		logger.error(f"Error getting past conversation: {e}")
		raise

async def get_session_agent_ids(session_id: str) -> set:
	"""The agents a session created by this API belongs to; empty when it never created one."""
	async with get_async_session() as session:
		res = await session.execute(
			select(ChatSessions.chatbot_id, ChatSessions.agent_id).where(ChatSessions.session_id == session_id)
		)
		return {agent for row in res.all() for agent in row if agent}

async def get_session_details(session_id: str, agent_id: str):
	"""
	Return dict with session_id, created_time, session_title or None.

	Args:
		session_id: The session ID to fetch
		agent_id: The agent ID
	"""
	try:
		logger.info(f"Fetching session details for session_id={session_id}, agent_id={agent_id}")
		async with get_async_session() as session:
			# Query by both chatbot_id and agent_id for backward compatibility
			from sqlalchemy import or_
			res = await session.execute(
				select(ChatSessions).where(
					ChatSessions.session_id == session_id,
					or_(ChatSessions.chatbot_id == agent_id, ChatSessions.agent_id == agent_id)
				)
			)
			row = res.first()
			if not row:
				return None
			obj = row[0] if isinstance(row, (tuple, Row)) else row
			# Sync agent_id with chatbot_id for backward compatibility
			if obj.chatbot_id and not obj.agent_id:
				obj.agent_id = obj.chatbot_id
				await session.commit()
			elif obj.agent_id and not obj.chatbot_id:
				obj.chatbot_id = obj.agent_id
				await session.commit()
			return {
				"session_id": obj.session_id,
				"created_time": obj.created_time,
				"session_title": obj.session_title
			}
	except Exception as e:
		logger.error(f"Error fetching session details: {e}")
		raise
	
async def add_session_title_to_db(session_id: str, session_title: str, updated_by: str = None):
	"""Rename a session.

	updated_by: acting dashboard user (email); None for internal / master-key callers.
	"""
	try:
		async with get_async_session() as session:
			res = await session.execute(select(ChatSessions).where(ChatSessions.session_id == session_id))
			obj = res.first()
			if not obj:
				return
			mapped_obj = obj[0] if isinstance(obj, (tuple, Row)) else obj
			mapped_obj.session_title = session_title
			mapped_obj.updated_at = datetime.utcnow()
			mapped_obj.updated_by = updated_by
			# Sync agent_id with chatbot_id for backward compatibility
			if mapped_obj.chatbot_id and not mapped_obj.agent_id:
				mapped_obj.agent_id = mapped_obj.chatbot_id
			elif mapped_obj.agent_id and not mapped_obj.chatbot_id:
				mapped_obj.chatbot_id = mapped_obj.agent_id
			await session.commit()
	except Exception as e:
		logger.error(f"Error adding session title to DB: {e}")
		raise

def _identity_candidates(*values: Optional[str]) -> List[str]:
	"""Every form a session's `user_id` might have been written as, for the given identities.

	Sessions are stored under whatever the caller authenticated as: the email for browser callers,
	and historically the users.user_id or the email's local part. De-duplicated, order preserved.
	"""
	candidates: List[str] = []
	for value in values:
		if not value:
			continue
		for form in (value, value.split('@')[0] if '@' in value else None):
			if form and form not in candidates:
				candidates.append(form)
	return candidates


async def _all_sessions_for_agent(agent_id: str) -> List[Dict]:
	"""Every non-deleted session on an agent, for callers with no user identity (master key)."""
	async with get_async_session() as session:
		from sqlalchemy import or_
		res = await session.execute(
			select(ChatSessions)
			.where(
				or_(ChatSessions.chatbot_id == agent_id, ChatSessions.agent_id == agent_id),
				(ChatSessions.deleted == False) | (ChatSessions.deleted.is_(None)),
			)
			.order_by(ChatSessions.created_time.desc())
		)
		return [_session_item(row[0] if isinstance(row, (tuple, Row)) else row) for row in res.all()]


def _session_item(row_obj, include_user: bool = False) -> Dict:
	"""Serialize one ChatSessions row for the API."""
	if row_obj.chatbot_id and not row_obj.agent_id:
		row_obj.agent_id = row_obj.chatbot_id
	elif row_obj.agent_id and not row_obj.chatbot_id:
		row_obj.chatbot_id = row_obj.agent_id
	item = {
		"session_id": row_obj.session_id,
		"created_time": row_obj.created_time,
		"display_message": row_obj.display_message,
		"session_title": row_obj.session_title,
	}
	if include_user:
		item["user_id"] = getattr(row_obj, "user_id", None)
	return item


async def get_guest_user_ids(owner_identity: str, agent_id: str) -> List[str]:
	"""Identities of users invited to this agent by its owner.

	`owner_identity` is the owner's email (or, for legacy agents, their user_id). It used to be
	turned into an email by appending "@gmail.com", which matched no invitation on a
	futuresmart.ai address, so the owner's guest view was always empty.
	"""
	try:
		async with get_async_session() as session:
			from sqlalchemy import or_
			owner_res = await session.execute(
				select(ChatbotDetails).where(
					or_(ChatbotDetails.chatbot_id == agent_id, ChatbotDetails.agent_id == agent_id),
					or_(
						func.lower(ChatbotDetails.owner_id) == (owner_identity or "").lower(),
						ChatbotDetails.user_id == owner_identity,
					),
				)
			)
			owner_row = owner_res.first()
		if not owner_row:
			logger.error(f"Owner {owner_identity} not found for agent {agent_id}")
			return []
		owner = owner_row[0] if isinstance(owner_row, (tuple, Row)) else owner_row
		owner_email = owner.owner_id or owner_identity

		async with get_async_session() as session:
			from sqlalchemy import or_
			res2 = await session.execute(
				select(ChatbotInvitations.invited_user_email).where(
					func.lower(ChatbotInvitations.invited_by_email) == (owner_email or "").lower(),
					or_(ChatbotInvitations.chatbot_id == agent_id, ChatbotInvitations.agent_id == agent_id)
				)
			)
			guest_emails = [row[0] for row in res2.all()]
		# Guests' sessions are stored under their email or its local part, same as owners'.
		return _identity_candidates(*guest_emails)
	except Exception as e:
		logger.error(f"Error getting guest user IDs: {e}")
		return []

async def retrieve_sessions(user_id: str, agent_id: str, show_guests_session: bool = False, email: str = None):
	"""
	Retrieve sessions for a user and agent.

	Args:
		user_id: The user ID
		agent_id: The agent ID
		show_guests_session: Whether to include guest sessions
		email: Optional email filter
	"""

	try:
		user_ids = []
		# Master-key / server-to-server callers arrive with no identity at all. Filtering on
		# `user_id IN (None)` matched nothing, so the endpoint returned [] for every agent. With no
		# identity to scope by, return the agent's sessions unfiltered.
		if not user_id and not email:
			return await _all_sessions_for_agent(agent_id)

		# Determine if the caller is the owner of this agent.
		# `owner_id` (the email) is what create_new_agent sets; `user_id` is NULL on every agent
		# created through the v1 API, so matching on it alone declared the real owner a stranger and
		# the invited-user check below then early-returned [].
		is_owner = False
		async with get_async_session() as session:
			from sqlalchemy import or_
			owner_conditions = []
			if email:
				owner_conditions.append(func.lower(ChatbotDetails.owner_id) == email.lower())
			if user_id:
				owner_conditions.append(ChatbotDetails.user_id == user_id)
			owner_q = await session.execute(
				select(ChatbotDetails).where(
					or_(ChatbotDetails.chatbot_id == agent_id, ChatbotDetails.agent_id == agent_id),
					or_(*owner_conditions),
				)
			)
			is_owner = owner_q.first() is not None
		# Resolve invited user's user_id if an email is provided (auth email)
		invited_user_id = None
		if email:
			invited_user_id = await get_user_id_from_email(email) or email.split('@')[0]
			# Validate invited relationship for this agent when using invited flow
			async with get_async_session() as session:
				from sqlalchemy import or_
				inv_q = await session.execute(
					select(ChatbotInvitations).where(
						or_(ChatbotInvitations.chatbot_id == agent_id, ChatbotInvitations.agent_id == agent_id),
						ChatbotInvitations.invited_user_email == email
					)
				)
				invited = inv_q.first()
				# Do not block owners who pass their own email
				if not invited and not is_owner:
					logger.warning(f"Email {email} is not an invited user for agent {agent_id}")
					return []
		# Build user_ids list based on show_guests_session and role.
		# `chat` stores ChatSessions.user_id as whatever the caller authenticated as — for browser
		# callers that is the EMAIL (api_validation sets auth["user_id"] to session_data["email"]),
		# while this function was handed the resolved users.user_id. Matching on one value alone
		# missed every session. Match on every form the writer could have used instead.
		if show_guests_session and is_owner:
			# Only invited guests' sessions; exclude the owner's own
			user_ids = await get_guest_user_ids(email or user_id, agent_id)
		else:
			user_ids = _identity_candidates(email, user_id, invited_user_id)
		async with get_async_session() as session:
			# Query by both chatbot_id and agent_id for backward compatibility
			from sqlalchemy import or_
			res = await session.execute(
				select(ChatSessions)
				.where(
					or_(ChatSessions.chatbot_id == agent_id, ChatSessions.agent_id == agent_id),
					ChatSessions.user_id.in_(user_ids),
					(ChatSessions.deleted == False) | (ChatSessions.deleted.is_(None))
				)
				.order_by(ChatSessions.created_time.desc())
			)
			rows = res.all()
			sessions = []
			for idx, row in enumerate(rows):
				logger.debug(f"Processing row: {row}, type: {type(row)}")
				# Always extract the first element if row is a tuple or Row
				row_obj = row[0] if isinstance(row, (tuple, Row)) else row
				# Sync agent_id with chatbot_id if needed
				if row_obj.chatbot_id and not row_obj.agent_id:
					row_obj.agent_id = row_obj.chatbot_id
				elif row_obj.agent_id and not row_obj.chatbot_id:
					row_obj.chatbot_id = row_obj.agent_id
				item = {
					"session_id": row_obj.session_id,
					"created_time": row_obj.created_time,
					"display_message": row_obj.display_message,
					"session_title": row_obj.session_title
				}
				if show_guests_session:
					item["user_id"] = getattr(row_obj, "user_id", None)
				sessions.append(item)
			# Commit any synced changes
			await session.commit()
			return sessions
	except Exception as e:
		logger.error(f"Error retrieving sessions: {e}")
		raise

async def retrieve_unqie_session_data(user_id: str, chatbot_id: str, session_id: str):
	try:
		logger.info(f"Checking authorization for user_id: {user_id}, chatbot_id: {chatbot_id}, session_id: {session_id}")
		async with get_async_session() as session:
			# fetch session
			res = await session.execute(select(ChatSessions).where(ChatSessions.session_id == session_id))
			chat_sess = res.first()
			if not chat_sess:
				return None
			# owner or invited-by-owner of this chatbot and session user
			is_owner = chat_sess.user_id == user_id
			owner_email = f"{user_id}@gmail.com"
			invq = await session.execute(
				select(ChatbotInvitations).where(
					ChatbotInvitations.chatbot_id == chatbot_id,
					ChatbotInvitations.invited_by_email == owner_email,
					ChatbotInvitations.invited_user_email.like(f"{chat_sess.user_id}%")
				)
			)
			is_guest = invq.first() is not None
			if not (is_owner or is_guest):
				logger.warning(f"User {user_id} is not authorized to view session {session_id}")
				return None
			if chat_sess.user_id == user_id and chat_sess.chatbot_id == chatbot_id and (chat_sess.deleted is False or chat_sess.deleted is None):
				return {
					"session_id": chat_sess.session_id,
					"created_time": chat_sess.created_time,
					"session_title": chat_sess.session_title
				}
			return None
	except Exception as e:
		logger.error(f"Error retrieving unique session data: {e}")
		raise

def _chart_for_replay(row) -> Optional[dict]:
	"""The chart to send back for a reopened turn, or None when there is no chart.

	The dashboard draws charts from `graph_output` and ignores `chart_output` entirely —
	which is why a live answer, which only ever sends `chart_output`, has never shown one.
	So the chart goes back under `graph_output`, in the `chart_*` key names the renderer
	expects.

	Prefers the block stored per turn; falls back to the older `graph_output` column, whose
	rows hold the agent's own `graph_*` spelling. A charts-off turn stored a placeholder
	there (`{"post_processing_query": ...}`) which is not a chart and must not be treated
	as one, or every such turn replays as a broken empty chart.
	"""
	stored = getattr(row, "chart_output", None)
	if isinstance(stored, dict) and any(
		stored.get(k) is not None for k in ("chart_suggestion", "chart_data", "metadata")
	):
		return stored

	legacy = getattr(row, "graph_output", None)
	if isinstance(legacy, dict) and any(
		legacy.get(k) is not None for k in ("graph_suggestion", "graph_data", "metadata")
	):
		return {
			"chart_suggestion": legacy.get("graph_suggestion"),
			"chart_data": legacy.get("graph_data"),
			"metadata": legacy.get("metadata"),
		}
	return None


async def get_session_data(session_id: str, *, agent_id: str, show_sql_query: bool, show_db_result: bool):
	"""A saved conversation — this agent's turns — under the agent's answer visibility settings.

	All three are required (no default) so every caller decides. Only `agent_id`'s turns are
	served: a session id can carry another agent's turns too (a chat service may send its own
	thread id to every agent it calls). Live chat leaves the SQL out when `show_sql_query` is
	off and the rows out when `show_db_result` is off, and a replay must not hand back what the
	live answer withheld. Pass the flags from `get_agent_with_visibility`, the same resolution
	live chat uses.
	"""
	try:
		logger.info(f"Getting session data for session_id: {session_id}")
		session_data = []
		async with get_async_session() as session:
			res = await session.execute(
				select(ChatLogs).where(
					ChatLogs.session_id == session_id, ChatLogs.agent_id == agent_id,
				).order_by(ChatLogs.created_at)
			)
			rows = res.all()
			logger.info(f"Found {len(rows) if rows else 0} messages for session {session_id}")
			if not rows:
				logger.warning(f"No conversation data found for session {session_id}")
				return None
			for row in rows:
				row_obj = row[0] if isinstance(row, (tuple, Row)) else row
				if getattr(row_obj, "user_query", None):
					user_message = {
						"chat_id": row_obj.chat_id,
						"role": "user",
						"message": row_obj.user_query,
						"timestamp": row_obj.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if row_obj.created_at else None,
						"debug_info": None,
						"graph_output": None
					}
					session_data.append(user_message)
				if getattr(row_obj, "gpt_response", None):
					assistant_message = {
						"chat_id": row_obj.chat_id,
						"role": "assistant",
						"message": row_obj.gpt_response,
						"timestamp": row_obj.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if row_obj.created_at else None,
						"user_feedback": row_obj.feedback
					}
					# Build debug info (no dedicated debug_info column in DB)
					if any([row_obj.user_query, row_obj.refined_query, row_obj.sql_query, row_obj.db_output]):
						debug_info = {
							"query": row_obj.user_query,
							"refine_query": row_obj.refined_query,
						}
						# Same omission as the live answer: the key is left out, not nulled.
						if show_sql_query:
							debug_info["sql_query"] = row_obj.sql_query
						if show_db_result:
							debug_info["db_output"] = row_obj.db_output
						assistant_message["debug_info"] = debug_info
					else:
						assistant_message["debug_info"] = None
					# The ONLY change to this payload: the chart is sent instead of a
					# hardcoded None. Every other key, debug_info included, is untouched.
					assistant_message["graph_output"] = _chart_for_replay(row_obj)
					# Additive: the column-labelled result block stored for this turn
					# ({columns, rows, row_count, truncated}); `db_output` above keeps bare rows
					# without column names. None for turns stored before the block existed, and
					# when the agent hides result rows.
					stored_debug = getattr(row_obj, "debug_info", None)
					assistant_message["result"] = (
						stored_debug.get("db_result") if show_db_result and isinstance(stored_debug, dict) else None
					)
					session_data.append(assistant_message)
		logger.info(f"Returning {len(session_data)} total messages for session {session_id}")
		return session_data
	except Exception as e:
		logger.error(f"Error getting session data: {e}")
		raise

async def get_session_chat_counter_from_db(session_id: str):
	try:
		from sqlalchemy import func
		async with get_async_session() as session:
			res = await session.execute(select(func.count()).select_from(ChatLogs).where(ChatLogs.session_id == session_id))
			count = res.first() or 0
			return count
	except Exception as e:
		logger.error(f"Error getting session chat counter: {e}")
		return None
				
async def add_user_feedback(session_id: str, chat_id: str, feedback: str, corrected_sql: str = None, *, agent_id: str):
	"""Record feedback on one of `agent_id`'s turns. A turn of another agent is not found, so a
	caller allowed to use one agent cannot rewrite another agent's stored verdict or SQL."""
	try:
		async with get_async_session() as session:
			res = await session.execute(select(ChatLogs).where(
				ChatLogs.session_id == session_id, ChatLogs.chat_id == chat_id, ChatLogs.agent_id == agent_id))
			row = res.first()
			if not row:
				return
			# Extract the actual SQLModel object from the tuple/Row
			row_obj = row[0] if isinstance(row, (tuple, Row)) else row
			row_obj.feedback = feedback
			# Store corrected SQL if provided (for rejected feedback)
			if corrected_sql:
				row_obj.sql_query = corrected_sql
			await session.commit()
	except Exception as e:
		logger.error(f"Error adding user feedback: {e}")
		raise

async def mark_session_as_deleted(session_id: str, user_id: str, agent_id: str, deleted_by: str = None) -> bool:
	"""
	Mark a session as deleted.

	Args:
		session_id: The session ID
		user_id: The user ID (ownership filter — which session may be deleted)
		agent_id: The agent ID
		deleted_by: Acting dashboard user (email); None for internal / master-key callers
	"""
	try:
		async with get_async_session() as session:
			# Query by both chatbot_id and agent_id for backward compatibility
			from sqlalchemy import or_
			res = await session.execute(
				select(ChatSessions).where(
					ChatSessions.session_id == session_id,
					ChatSessions.user_id == user_id,
					or_(ChatSessions.chatbot_id == agent_id, ChatSessions.agent_id == agent_id),
					(ChatSessions.deleted == False) | (ChatSessions.deleted.is_(None))
				)
			)
			obj = res.first()
			if not obj:
				logger.error(f"Session not found or already deleted: session_id={session_id}, user_id={user_id}, agent_id={agent_id}")
				return False
			mapped_obj = obj[0] if isinstance(obj, (tuple, Row)) else obj
			mapped_obj.deleted = True
			mapped_obj.updated_at = datetime.utcnow()
			mapped_obj.deleted_at = datetime.utcnow()
			mapped_obj.deleted_by = deleted_by
			# Sync agent_id with chatbot_id for backward compatibility
			if mapped_obj.chatbot_id and not mapped_obj.agent_id:
				mapped_obj.agent_id = mapped_obj.chatbot_id
			elif mapped_obj.agent_id and not mapped_obj.chatbot_id:
				mapped_obj.chatbot_id = mapped_obj.agent_id
			await session.commit()
			return True
	except Exception as e:
		logger.error(f"Error marking session as deleted: {e}")
		raise

async def retrieve_sessions_for_users(user_ids: List[str], chatbot_id: str) -> List[Dict]:
	"""Retrieve sessions for multiple user_ids."""
	async with get_async_session() as session:
		res = await session.execute(
			select(ChatSessions)
			.where(
				ChatSessions.chatbot_id == chatbot_id,
				ChatSessions.user_id.in_(user_ids),
				(ChatSessions.deleted == False) | (ChatSessions.deleted.is_(None))
			)
			.order_by(ChatSessions.created_time.desc())
		)
		rows = res.all()
		return [
			{
				"session_id": r.session_id,
				"created_time": r.created_time,
				"display_message": r.display_message,
				"session_title": r.session_title,
				"user_id": r.user_id
			}
			for r in rows
		]

