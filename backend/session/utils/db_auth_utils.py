import mysql.connector
from mysql.connector.errors import Error
import os
from datetime import datetime
from session.services.logger import logger

# host=os.getenv("DB_HOST")
# user=os.getenv("DB_USER")
# password=os.getenv("DB_PASSWORD")
# database=os.getenv("DB_NAME")
# port=os.getenv("DB_PORT")

refresh_limit = os.getenv("REFRESH_LIMIT")
ambassador_user_limit = int(os.getenv("AMBASSADOR_USER_LIMIT"))
team_user_limit = int(os.getenv("TEAM_MEMBER_USER_LIMIT"))
user_limit = int(os.getenv("USER_LIMIT"))
chat_user_limit = int(os.getenv("CHAT_USER_LIMIT"))
admin_user_limit = int(os.getenv("ADMIN_USER_LIMIT"))
mode = os.getenv("MODE")
admin_users = os.getenv("ADMIN_USERS")

# from session.db_utils.common_postresql_utils import execute_sql_query, db_rows_affected_log

async def log_user(user_id="", user_email="", user_name="", user_pic="", first_logged_in="", last_accessed=""):
    try:
        sql_query = """SELECT COUNT(*) from users WHERE email_id = $1"""
        params = (user_email,)
        row_count = await execute_sql_query(sql_query, *params, fetchval=True)
        logger.info(f"row_count: {row_count}")
        if row_count == 0:
            sql_query = """INSERT INTO users (user_id, email_id, user_name, user_pic, first_logged_in, last_accessed) VALUES ($1, $2, $3, $4, $5, $6)"""
            params = (user_id, user_email, user_name, user_pic, first_logged_in, last_accessed)
            row_count = await execute_sql_query(sql_query, *params)
            db_rows_affected_log(row_count, "User logged in successfully", "Failed to log user")
    except Exception as e:
        logger.error(f"Error logging user: {e}")

# def log_user(user_id="", user_email="", user_name="", user_pic="", first_logged_in="", last_accessed=""):
#     try:
#         connection = mysql.connector.connect(host=host, database=database, user=user, password=password)
#         if connection.is_connected():
#             cursor = connection.cursor()
#             sql_query = """SELECT COUNT(*) from users WHERE email_id = %s"""
#             cursor.execute(sql_query, (user_email,))
#             row_count = cursor.fetchone()[0]
            
#             if row_count == 0:
#                 sql_query = """INSERT INTO users (user_id, email_id, user_name, user_pic, first_logged_in, last_accessed) VALUES (%s, %s, %s, %s, %s, %s)"""
#                 cursor.execute(sql_query, (user_id, user_email, user_name, user_pic, first_logged_in, last_accessed))

#             # Commit changes
#             connection.commit()
#             logger.info("Record inserted successfully")

#     except Error as e:
#         logger.info("Error while connecting to MySQL", e)
#     finally:
#         if connection.is_connected():
#             cursor.close()
#             connection.close()
#             logger.info("MySQL connection is closed")

async def update_service_count(user_email, request_count=1, service="aidemos"):
    try:
        sql_query = """SELECT service_count, last_accessed, tier FROM users WHERE email_id = $1"""
        params = (user_email,)
        result = await execute_sql_query(sql_query, *params, fetchone=True)
        if result:
            current_count = result['service_count']
            last_accessed = result['last_accessed']
            user_tier = result['tier']
            curr_time = datetime.utcnow()
            time_difference = curr_time - last_accessed
            hours_difference = time_difference.total_seconds() / 3600
            
            if hours_difference >= float(refresh_limit):
                final_count = current_count
                query = "UPDATE users SET total_requests = total_requests + $1 WHERE email_id = $2"
                params = (final_count, user_email)
                row_count = await execute_sql_query(query, *params)
                db_rows_affected_log(row_count, "Total requests updated successfully", "Request limit is above the limit")
                total_count = 0 + request_count
            else:
                total_count = current_count + request_count
                logger.info(f"Incrementing count to {total_count}")
                
            if user_tier == "Ambassador":
                new_user_limit = ambassador_user_limit
            elif user_tier == "Team Member":
                new_user_limit = team_user_limit
            elif user_tier == "Admin" or user_email in admin_users:
                logger.info("Admin User: No restrictions")
                new_user_limit = admin_user_limit
            else:
                if service == "chat":
                    new_user_limit = chat_user_limit
                else:
                    new_user_limit = user_limit
            
            logger.debug(f"User limit for tier {user_tier}: {new_user_limit}")
            
            if total_count <= new_user_limit:
                query = "UPDATE users SET service_count = $1, last_accessed =$2 WHERE email_id = $3"
                params = (total_count, curr_time, user_email)
                row_count = await execute_sql_query(query, *params)
                db_rows_affected_log(row_count, "User logged in successfully", "Failed to log user")
                return True, total_count
            else:
                logger.warning(f"Service count limit exceeded for user {user_email}")
                return False, total_count
        else:
            logger.error(f"User not found: {user_email}")
            return False, "User not found"
    except Exception as e:
        logger.error(f"Error updating service count: {e}")
    return False, "Database error"
                             
# def update_service_count(user_email, request_count=1, service="aidemos"):
#     try:
#         logger.info(f"Attempting to update service count for user: {user_email}")
#         connection = mysql.connector.connect(host=host, database=database, user=user, password=password)

#         if connection.is_connected():
#             logger.info("Database connection established")
#             cursor = connection.cursor()

#             cursor.execute("SET SESSION transaction_isolation = 'SERIALIZABLE'")
#             connection.start_transaction()
#             curr_time = datetime.utcnow()

#             # Lock the row and get the current count
#             query = "SELECT service_count, last_accessed, tier FROM users WHERE email_id = %s"
#             cursor.execute(query, (user_email,))

#             result = cursor.fetchone()

#             if result:
#                 current_count = result[0]
#                 last_accessed = result[1]
#                 user_tier = result[2]
#                 time_difference = curr_time - last_accessed
#                 hours_difference = time_difference.total_seconds() / 3600

#                 logger.info(f"Current count: {current_count}, Last accessed: {last_accessed}, User tier: {user_tier}")

#                 if hours_difference >= float(refresh_limit):
#                     logger.info(f"Refresh period elapsed for user {user_email}. Resetting count.")
#                     final_count = current_count
#                     query = "UPDATE users SET total_requests = total_requests + %s WHERE email_id = %s"
#                     cursor.execute(query, (final_count,user_email))
#                     connection.commit()
#                     total_count = 0 + request_count
#                 else:
#                     total_count = current_count + request_count
#                     logger.info(f"Incrementing count to {total_count}")

#                 if user_tier == "Ambassador":
#                     new_user_limit = ambassador_user_limit
#                 elif user_tier == "Team Member":
#                     new_user_limit = team_user_limit
#                 elif user_tier == "Admin" or user_email in admin_users:
#                     logger.info("Admin User: No restrictions")
#                     new_user_limit = admin_user_limit
#                 else:
#                     if service == "chat":
#                         new_user_limit = chat_user_limit
#                     else:
#                         new_user_limit = user_limit

#                 logger.debug(f"User limit for tier {user_tier}: {new_user_limit}")

#                 if total_count <= new_user_limit:
#                     # Increment the count
#                     query = "UPDATE users SET service_count = %s, last_accessed =%s WHERE email_id = %s"
#                     cursor.execute(
#                         query,
#                         (
#                             total_count,
#                             curr_time,
#                             user_email,
#                         ),
#                     )
#                     connection.commit()
#                     logger.info(f"Successfully updated service count for {user_email} to {total_count}")
#                     return True, total_count
#                 else:
#                     connection.rollback()
#                     logger.warning(f"Service count limit exceeded for user {user_email}")
#                     return False, total_count
#             else:
#                 connection.rollback()
#                 logger.error(f"User not found: {user_email}")
#                 return False, "User not found"

#     except Exception as e:
#         print(f"An error occurred: {e}")
#         connection.rollback()
#     finally:
#         if connection.is_connected():
#             cursor.close()
#             connection.close()
#             logger.info("MySQL connection is closed")

#     return False, "Database error"

async def log_token(access_token, user_email, session_id):
    try:
        sql_query = """INSERT INTO issued_tokens (token, email_id, session_id) VALUES ($1, $2, $3)"""
        params = (access_token, user_email, session_id)
        row_count = await execute_sql_query(sql_query, *params)
        db_rows_affected_log(row_count, "Token logged in successfully", "Failed to log token")
    except Exception as e:
        logger.error(f"Error logging token: {e}")
        
# def log_token(access_token, user_email, session_id):
    # try:
    #     connection = mysql.connector.connect(host=host, database=database, user=user, password=password)

    #     if connection.is_connected():
    #         cursor = connection.cursor()

    #         # SQL query to insert data
    #         sql_query = """INSERT INTO issued_tokens (token, email_id, session_id) VALUES (%s,%s,%s)"""
    #         # Execute the SQL query
    #         cursor.execute(sql_query, (access_token, user_email, session_id))

    #         # Commit changes
    #         connection.commit()
    #         logger.info("Record inserted successfully")

    # except Error as e:
    #     logger.info("Error while connecting to MySQL", e)
    # finally:
    #     if connection.is_connected():
    #         cursor.close()
    #         connection.close()
    #         logger.info("MySQL connection is closed")

async def get_service_count(user_email):
    try:
        sql_query = """SELECT service_count FROM users WHERE email_id = $1"""
        params = (user_email,)
        result = await execute_sql_query(sql_query, *params, fetchone=True)
        return result['service_count']
    except Exception as e:
        logger.error(f"Error getting service count: {e}")
        return None
# def get_service_count(user_email):
#     try:
#         connection = mysql.connector.connect(host=host, database=database, user=user, password=password)

#         if connection.is_connected():
#             cursor = connection.cursor()

#             # SQL query to insert data
#             sql_query = """SELECT service_count FROM users 
#                             WHERE email_id = %s"""

#             # Execute the SQL query
#             cursor.execute(sql_query, (user_email,))

#             result = cursor.fetchone()

#             if result:
#                 # Extract the value from the result tuple
#                 service_count = result[0]
#             else:
#                 logger.info("User not found")
#             # Commit changes
#             connection.commit()

#     except Error as e:
#         logger.info("Error while connecting to MySQL", e)
#     finally:
#         if connection.is_connected():
#             cursor.close()
#             connection.close()
#             logger.info("MySQL connection is closed")
#     return service_count

async def get_user_details(user_email):
    try:
        sql_query = """SELECT user_id, user_name, user_pic, service_count, tier, last_accessed FROM users WHERE email_id = $1"""
        params = (user_email,)
        result = await execute_sql_query(sql_query, *params, fetchone=True)
        if result:
            logger.info(f"User Found: {result}")
            return result
        else:
            logger.info(f"No user found with the email: {user_email}")
            return None
    except Exception as e:
        logger.error(f"Error getting user details: {e}")
        return None
    
# def get_user_details(user_email):
#     try:
#         connection = mysql.connector.connect(host=host, database=database, user=user, password=password)

#         if connection.is_connected():
#             cursor = connection.cursor(dictionary=True)

#             sql_query = """SELECT user_id, user_name, user_pic, service_count, tier, last_accessed FROM users WHERE email_id = %s"""
#             cursor.execute(sql_query, (user_email,))
#             user_details = cursor.fetchone()

#             if user_details:
#                 logger.info("User Found:", user_details)
#                 return user_details
#             else:
#                 logger.info("No user found with the email:", user_email)
#                 return None

#     except Error as e:
#         logger.info("Error while connecting to MySQL", e)
#         return None
#     finally:
#         if connection and connection.is_connected():
#             cursor.close()
#             connection.close()
#             logger.info("MySQL connection is closed")

async def get_user_session_id(user_email, token):
    try:
        sql_query = """SELECT session_id FROM issued_tokens WHERE email_id = $1 AND token = $2"""
        params = (user_email, token)
        result = await execute_sql_query(sql_query, *params, fetchone=True)
        if result:
            logger.info("Found session details for the provided email and token.")
            return result['session_id']
        else:
            logger.info(f"No session found with the provided email and token: {user_email} and {token}")
            return None
    except Exception as e:
        logger.error(f"Error getting user session ID: {e}")
        return None
    
# def get_user_session_id(user_email, token):
#     try:
#         connection = mysql.connector.connect(host=host, database=database, user=user, password=password)

#         if connection.is_connected():
#             cursor = connection.cursor(dictionary=True)

#             sql_query = """SELECT session_id FROM issued_tokens WHERE email_id = %s AND token = %s"""
#             cursor.execute(sql_query, (user_email, token))
#             session_details = cursor.fetchone()

#             if session_details:
#                 logger.info("Found session details for the provided email and token.")
#                 return session_details["session_id"]
#             else:
#                 logger.info("No session found with the provided email and token.")
#                 return None
#     except Error as e:
#         logger.info("Error while connecting to MySQL", e)
#         return None
#     finally:
#         if connection and connection.is_connected():
#             cursor.close()
#             connection.close()
#             logger.info("MySQL connection is closed")

    
def get_energy(service_count, user_email, user_tier, service="aidemos"):
    if user_tier == "Ambassador":
        energy = ambassador_user_limit - service_count
    elif user_tier == "Team Member":
        energy = team_user_limit - service_count
    elif user_tier == "Admin" or user_email in admin_users:
        logger.info("Admin User: No restrictions")
        energy = admin_user_limit
    else:
        if service == "chat":
            energy = chat_user_limit - service_count
        else:
            energy = user_limit - service_count

    logger.info(f"User limit for tier {user_tier}: {energy}")
    return energy