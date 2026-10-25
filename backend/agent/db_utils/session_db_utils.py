import time
import json
from datetime import datetime, timedelta
from agent.db_utils.common_db_utils import get_connection
from agent.db_utils.common_postresql_utils import execute_sql_query, db_rows_affected_log
from otel_tracing import track_time

import pymysql
from uuid import uuid4
from logger import logger
from typing import List, Dict
from sqlmodel import select
from models.sql_models import ChatbotInvitations, ChatbotDetails, ChatSessions, ChatLogs
from agent.services.sqlmodel_session import get_async_session
from sqlalchemy.engine.row import Row


async def log_new_session(user_id, agent_id, user_query):
	"""
	Create a new chat session.

	Args:
		user_id: User ID (can be None for new RESTful endpoints)
		agent_id: Agent ID
		user_query: The user's query
	"""
	try:
		session_id = str(uuid4())
		session_title = user_query[:25] + '...' if len(user_query) > 25 else user_query
		display_message = user_query
		async for session in get_async_session():
			obj = ChatSessions(
				session_id=session_id,
				chatbot_id=agent_id,  # Store agent_id in chatbot_id column for backward compatibility
				agent_id=agent_id,  # Sync both IDs for consistency
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

def chat_log_history(rows):
	"""Conversation context for the model, oldest first.

	A turn the agent did not answer keeps its question but not its reply: the
	refusal says nothing about the schema, and replaying it made the next turn
	refuse a question the schema supports (DA-ANSWERABILITY-001). Each turn
	decides schema support again.
	"""
	messages = []
	for chat_log in rows:
		if chat_log.user_query:
			messages.append({"role": "user", "content": chat_log.user_query})
		if chat_log.gpt_response and chat_log.is_answered is not False:
			messages.append({"role": "assistant", "content": chat_log.gpt_response})
	return messages


async def get_past_conversation(session_id):
	try:
		start_time = time.time()
		messages = []
		async for session in get_async_session():
			res = await session.execute(
				select(ChatLogs).where(ChatLogs.session_id == session_id).order_by(ChatLogs.created_at)
			)
			rows = res.scalars().all()  # Use scalars() to get objects directly, not tuples
			messages.extend(chat_log_history(rows))
		elapsed_time = time.time() - start_time
		logger.info(f"History For Context(get_conversation):{messages}, elapsed_time: {elapsed_time}")
		return messages
	except Exception as e:
		logger.error(f"Error getting past conversation: {e}")
		raise
	
@track_time("DB: Add Session Title")
async def add_session_title_to_db(session_id: str, session_title: str, updated_by: str = None):
	"""Rename a session.

	updated_by: acting dashboard user (email); None for internal / master-key callers.
	"""
	try:
		async for session in get_async_session():
			res = await session.execute(select(ChatSessions).where(ChatSessions.session_id == session_id))
			obj = res.first()
			if not obj:
				return
			# res.first() yields a Row; unwrap to the mapped ChatSessions before mutating.
			mapped_obj = obj[0] if isinstance(obj, (tuple, Row)) else obj
			mapped_obj.session_title = session_title
			mapped_obj.updated_at = datetime.utcnow()
			mapped_obj.updated_by = updated_by
			await session.commit()
	except Exception as e:
		logger.error(f"Error adding session title to DB: {e}")
		raise

async def get_guest_user_ids(admin_user_id: str, agent_id: str) -> List[str]:
	"""
	Get list of guest user IDs for a given agent and admin user.

	Args:
		admin_user_id: Admin user ID
		agent_id: Agent ID
	"""
	try:
		# First get the admin's email
		async for session in get_async_session():
			res = await session.execute(
				select(ChatbotDetails).where(ChatbotDetails.user_id == admin_user_id)
			)
			owner = res.first()
		if not owner:
			logger.error(f"Admin user {admin_user_id} not found")
			return []
		admin_email = admin_user_id+"@gmail.com"
		# Get guest emails from chatbot_invitations
		# Query by agent_id OR chatbot_id for backward compatibility
		from sqlalchemy import or_
		async for session in get_async_session():
			res2 = await session.execute(
				select(ChatbotInvitations.invited_user_email).where(
					ChatbotInvitations.invited_by_email == admin_email,
					or_(
						ChatbotInvitations.chatbot_id == agent_id,
						ChatbotInvitations.agent_id == agent_id
					)
				)
			)
			guest_emails = res2.all()
		if not guest_emails:
			return []
		guest_user_ids = [email for email, in guest_emails] if isinstance(guest_emails[0], tuple) else [email.invited_user_email for email in guest_emails]
		# Extract user_ids from emails (part before @)
		guest_user_ids = [e.split('@')[0] for e in guest_user_ids]
		return guest_user_ids
	except Exception as e:
		logger.error(f"Error getting guest user IDs: {e}")
		return []

async def retrieve_sessions(user_id: str, agent_id: str, show_guests_session: bool = False, email: str = None):
	"""
	Retrieve sessions for a user and agent.

	Args:
		user_id: User ID (can be None for new RESTful endpoints)
		agent_id: Agent ID
		show_guests_session: Whether to include guest sessions
		email: Optional email filter
	"""
	try:
		user_ids = []
		# If email is provided, check if it's an invited user
		from sqlalchemy import or_
		if email:
			async for session in get_async_session():
				res = await session.execute(
					select(ChatbotInvitations).where(
						ChatbotInvitations.invited_user_email == email,
						or_(
							ChatbotInvitations.chatbot_id == agent_id,
							ChatbotInvitations.agent_id == agent_id
						)
					)
				)
				invited = res.first()
			if not invited:
				logger.warning(f"Email {email} is not an invited user for agent {agent_id}")
				return []
			user_id_from_email = email.split('@')[0]
			user_ids = [user_id_from_email]
			if show_guests_session:
				guest_user_ids = await get_guest_user_ids(user_id, agent_id)
				user_ids.extend(guest_user_ids)
		else:
			user_ids = [user_id]
			if show_guests_session:
				guest_user_ids = await get_guest_user_ids(user_id, agent_id)
				user_ids.extend(guest_user_ids)
		async for session in get_async_session():
			res = await session.execute(
				select(ChatSessions)
				.where(
					or_(
						ChatSessions.chatbot_id == agent_id,
						ChatSessions.agent_id == agent_id
					),
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
				item = {
					"session_id": row_obj.session_id,
					"created_time": row_obj.created_time,
					"display_message": row_obj.display_message,
					"session_title": row_obj.session_title
				}
				if show_guests_session:
					item["user_id"] = getattr(row_obj, "user_id", None)
				sessions.append(item)
			return sessions
	except Exception as e:
		logger.error(f"Error retrieving sessions: {e}")
		raise

async def retrieve_unqie_session_data(user_id: str, agent_id: str, session_id: str):
	"""
	Retrieve unique session data with authorization check.

	Args:
		user_id: User ID (can be None for new RESTful endpoints)
		agent_id: Agent ID
		session_id: Session ID
	"""
	try:
		from sqlalchemy import or_
		logger.info(f"Checking authorization for user_id: {user_id}, agent_id: {agent_id}, session_id: {session_id}")
		async for session in get_async_session():
			# fetch session
			res = await session.execute(select(ChatSessions).where(ChatSessions.session_id == session_id))
			chat_sess = res.first()
			if not chat_sess:
				return None
			# owner or invited-by-owner of this agent and session user
			is_owner = chat_sess.user_id == user_id
			owner_email = f"{user_id}@gmail.com"
			invq = await session.execute(
				select(ChatbotInvitations).where(
					or_(
						ChatbotInvitations.chatbot_id == agent_id,
						ChatbotInvitations.agent_id == agent_id
					),
					ChatbotInvitations.invited_by_email == owner_email,
					ChatbotInvitations.invited_user_email.like(f"{chat_sess.user_id}%")
				)
			)
			is_guest = invq.first() is not None
			if not (is_owner or is_guest):
				logger.warning(f"User {user_id} is not authorized to view session {session_id}")
				return None
			# Check if session belongs to this agent (query both chatbot_id and agent_id)
			session_matches = (chat_sess.chatbot_id == agent_id or chat_sess.agent_id == agent_id)
			if chat_sess.user_id == user_id and session_matches and (chat_sess.deleted is False or chat_sess.deleted is None):
				return {
					"session_id": chat_sess.session_id,
					"created_time": chat_sess.created_time,
					"session_title": chat_sess.session_title
				}
			return None
	except Exception as e:
		logger.error(f"Error retrieving unique session data: {e}")
		raise

async def get_session_data(session_id: str):
	try:
		logger.info(f"Getting session data for session_id: {session_id}")
		session_data = []
		async for session in get_async_session():
			res = await session.execute(
				select(ChatLogs).where(ChatLogs.session_id == session_id).order_by(ChatLogs.created_at)
			)
			rows = res.all()
			logger.info(f"Found {len(rows) if rows else 0} messages for session {session_id}")
			if not rows:
				logger.warning(f"No conversation data found for session {session_id}")
				return None
			for row in rows:
				if row.user_query:
					user_message = {
						"chat_id": row.chat_id,
						"role": "user",
						"message": row.user_query,
						"timestamp": row.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if row.created_at else None,
						"debug_info": {
							"query": row.user_query,
							"refine_query": row.refined_query,
							"sql_query": row.sql_query,
							"db_output": row.db_output
						} if any([row.user_query, row.refined_query, row.sql_query, row.db_output]) else None,
						"chart_output": getattr(row, "graph_output", None)
					}
					session_data.append(user_message)
				if row.gpt_response:
					assistant_message = {
						"chat_id": row.chat_id,
						"role": "assistant",
						"message": row.gpt_response,
						"timestamp": row.created_at.strftime("%Y-%m-%dT%H:%M:%SZ") if row.created_at else None,
						"user_feedback": row.feedback
					}
					# Build debug info (no dedicated debug_info column in DB)
					if any([row.user_query, row.refined_query, row.sql_query, row.db_output]):
						assistant_message["debug_info"] = {
							"query": row.user_query,
							"refine_query": row.refined_query,
							"sql_query": row.sql_query,
							"db_output": row.db_output
						}
					else:
						assistant_message["debug_info"] = None
					assistant_message["chart_output"] = getattr(row, "graph_output", None)
					session_data.append(assistant_message)
		logger.info(f"Returning {len(session_data)} total messages for session {session_id}")
		return session_data
	except Exception as e:
		logger.error(f"Error getting session data: {e}")
		raise

async def get_session_chat_counter_from_db(session_id: str):
	try:
		from sqlalchemy import func
		async for session in get_async_session():
			res = await session.execute(select(func.count()).select_from(ChatLogs).where(ChatLogs.session_id == session_id))
			count = res.first() or 0
			return count
	except Exception as e:
		logger.error(f"Error getting session chat counter: {e}")
		return None
				
async def add_user_feedback(session_id: str, chat_id: str, feedback: str):
	try:
		async for session in get_async_session():
			res = await session.execute(select(ChatLogs).where(ChatLogs.session_id == session_id, ChatLogs.chat_id == chat_id))
			row = res.first()
			if not row:
				return
			row.feedback = feedback
			await session.commit()
	except Exception as e:
		logger.error(f"Error adding user feedback: {e}")
		raise

async def mark_session_as_deleted(session_id: str, user_id: str, agent_id: str, deleted_by: str = None) -> bool:
	"""
	Mark a session as deleted.

	Args:
		session_id: Session ID
		user_id: User ID (ownership filter; can be None for new RESTful endpoints)
		agent_id: Agent ID
		deleted_by: Acting dashboard user (email); None for internal / master-key callers
	"""
	try:
		from sqlalchemy import or_
		async for session in get_async_session():
			res = await session.execute(
				select(ChatSessions).where(
					ChatSessions.session_id == session_id,
					ChatSessions.user_id == user_id,
					or_(
						ChatSessions.chatbot_id == agent_id,
						ChatSessions.agent_id == agent_id
					),
					(ChatSessions.deleted == False) | (ChatSessions.deleted.is_(None))
				)
			)
			obj = res.first()
			if not obj:
				logger.error(f"Session not found or already deleted: session_id={session_id}, user_id={user_id}, agent_id={agent_id}")
				return False
			# res.first() yields a Row; unwrap to the mapped ChatSessions before mutating.
			mapped_obj = obj[0] if isinstance(obj, (tuple, Row)) else obj
			mapped_obj.deleted = True
			mapped_obj.updated_at = datetime.utcnow()
			mapped_obj.deleted_at = datetime.utcnow()
			mapped_obj.deleted_by = deleted_by
			await session.commit()
			return True
	except Exception as e:
		logger.error(f"Error marking session as deleted: {e}")
		raise

async def retrieve_sessions_for_users(user_ids: List[str], agent_id: str) -> List[Dict]:
	"""
	Retrieve sessions for multiple user_ids.

	Args:
		user_ids: List of user IDs
		agent_id: Agent ID
	"""
	from sqlalchemy import or_
	async for session in get_async_session():
		res = await session.execute(
			select(ChatSessions)
			.where(
				or_(
					ChatSessions.chatbot_id == agent_id,
					ChatSessions.agent_id == agent_id
				),
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

