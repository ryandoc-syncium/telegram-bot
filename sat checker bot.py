import os
import logging
import sqlite3
import threading
import telebot
import atexit
from fractions import Fraction
import math

ADMIN_USER_ID = 1471789118  # Replace this with your Telegram user ID

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize bot
bot = telebot.TeleBot(os.getenv('TELEGRAM_BOT_TOKEN'))

# Thread-local storage for database connections
thread_local = threading.local()

def get_db_connection():
    if not hasattr(thread_local, "conn"):
        thread_local.conn = sqlite3.connect('tests.db', check_same_thread=False)
        thread_local.cursor = thread_local.conn.cursor()
    return thread_local.conn, thread_local.cursor

def execute_db_query(query, params=()):
    conn, cursor = get_db_connection()
    try:
        cursor.execute(query, params)
        conn.commit()
        return True
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        return False

# Ensure the 'tests' table exists
conn, cursor = get_db_connection()
cursor.execute('''
CREATE TABLE IF NOT EXISTS tests (
    test_code TEXT,
    part TEXT,
    answer_key TEXT NOT NULL,
    PRIMARY KEY (test_code, part)
)
''')
conn.commit()

cursor.execute('''
CREATE TABLE IF NOT EXISTS student_results (
    student_name TEXT,
    test_code TEXT,
    part TEXT,
    student_answers TEXT,
    score INTEGER,
    mistakes TEXT,
    PRIMARY KEY (student_name, test_code, part)
)
''')
conn.commit()

# Ensure 'mistakes' column exists in 'student_results'
cursor.execute("PRAGMA table_info(student_results);")
columns = [column[1] for column in cursor.fetchall()]
if 'mistakes' not in columns:
    cursor.execute("ALTER TABLE student_results ADD COLUMN mistakes TEXT;")
    conn.commit()
    logger.info("Added 'mistakes' column to 'student_results' table.")

# Ensure 'part' column exists in 'student_results'
cursor.execute("PRAGMA table_info(student_results);")
columns = [column[1] for column in cursor.fetchall()]
if 'part' not in columns:
    print("Adding 'part' column to 'student_results' table...")
    cursor.execute("ALTER TABLE student_results ADD COLUMN part TEXT;")
    conn.commit()
    print("'part' column added successfully.")
else:
    # Column already exists, no action needed
    pass


# Close database connection on exit
@atexit.register
def close_connection():
    if hasattr(thread_local, "conn"):
        thread_local.conn.close()
        logger.info("Database connection closed.")

# Command: Start
@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "Welcome! Use /help to learn how to use this bot.")

# Command: Help
@bot.message_handler(commands=['help'])
def help_command(message):
    help_text = """
Welcome to the SAT Test Bot! Here are the available commands:

/addtest <code> <part> <answer_key> - Add a new test part (math or english).
/viewtest <code> <part> - View the answer key for a specific test part.
/removetest <code> - Remove a test (both parts) from the database.
/studentscores <name> - View scores for a specific student.
/updatetest <code> <part> <new_answer_key> - Update the answer key for a test part.
/rankings <test_code> - View rankings for a specific test.
/progress <student_name> - View progress for a specific student.
/deletesubmission <student_name> <test_code> <part> - Delete a student's submission for a specific test part.
Submit answers: <test_code>_<part>*<answers> - Submit your answers for a test part.

Example for Math: math01_math*2,6,3/2,7,3.14
Example for English: math01_english*a,b,c,d,a,b,c,d
"""
    bot.send_message(message.chat.id, help_text)

# Command: Add Test (Restricted to Admin)
@bot.message_handler(commands=['addtest'])
def add_test(message):
    if message.from_user.id != ADMIN_USER_ID:
        bot.send_message(message.chat.id, "You are not authorized to use this command.")
        return

    try:
        _, test_code, part, answer_key = message.text.split(' ', 3)
        part = part.lower()

        if part not in ["math", "english"]:
            raise ValueError("Part must be 'math' or 'english'.")

        # Check if the test part already exists
        conn, cursor = get_db_connection()
        cursor.execute('SELECT answer_key FROM tests WHERE test_code = ? AND part = ?', (test_code, part))
        if cursor.fetchone():
            bot.send_message(message.chat.id, f"Test '{test_code}' for part '{part}' already exists.")
            return

        # Check the number of answers
        expected_answers = 44 if part == "math" else 54
        actual_answers = len(answer_key.split(';'))
        if actual_answers != expected_answers:
            raise ValueError(f"Expected {expected_answers} answers, but got {actual_answers}.")

        # Insert into the database
        if not execute_db_query('INSERT INTO tests (test_code, part, answer_key) VALUES (?, ?, ?)', 
                              (test_code, part, answer_key)):
            raise ValueError("Failed to execute database query.")

        bot.send_message(message.chat.id, f"Answer key for {part} part of test '{test_code}' added successfully.")
    except ValueError as e:
        logger.error(f"Error in /addtest: {e}")
        bot.send_message(message.chat.id, f"Error: {e}\nUsage: /addtest <code> <part> <answer_key>")
    except Exception as e:
        logger.error(f"Unexpected error in /addtest: {e}")
        bot.send_message(message.chat.id, "Failed to add test. Please try again.")



# Command: View Test
@bot.message_handler(commands=['viewtest'])
def view_test(message):
    try:
        _, test_code, part = message.text.split(' ', 2)
        part = part.lower()

        if part not in ["math", "english"]:
            raise ValueError("Part must be 'math' or 'english'.")

        # Fetch the answer key
        conn, cursor = get_db_connection()  # Use the function to get the cursor
        cursor.execute('SELECT answer_key FROM tests WHERE test_code = ? AND part = ?', (test_code, part))
        result = cursor.fetchone()

        if not result:
            bot.send_message(message.chat.id, f"Test '{test_code}' for part '{part}' not found.")
            return

        # Format the answer key
        answer_key = result[0].split(';')
        response = f"Answer key for {part} part of test '{test_code}':\n"
        for i, answer in enumerate(answer_key, start=1):
            response += f"Q{i}: {answer}\n"

        bot.send_message(message.chat.id, response)
    except ValueError:
        bot.send_message(message.chat.id, "Usage: /viewtest <code> <part>")


# Command: Remove Test (Restricted to Admin)
@bot.message_handler(commands=['removetest'])
def remove_test(message):
    if message.from_user.id != ADMIN_USER_ID:
        bot.send_message(message.chat.id, "You are not authorized to use this command.")
        return

    try:
        _, test_code = message.text.split(' ', 1)

        # Check if the test exists
        conn, cursor = get_db_connection()
        cursor.execute('SELECT * FROM tests WHERE test_code = ?', (test_code,))
        if not cursor.fetchone():
            bot.send_message(message.chat.id, f"Test '{test_code}' not found.")
            return

        # Remove both Math and English parts
        if not execute_db_query('DELETE FROM tests WHERE test_code = ?', (test_code,)):
            bot.send_message(message.chat.id, "Failed to remove test. Please try again.")
            return

        bot.send_message(message.chat.id, f"Test '{test_code}' (both parts) has been removed.")
    except ValueError:
        bot.send_message(message.chat.id, "Usage: /removetest <code>")

# Command: View Student Scores (Restricted to Admin)
@bot.message_handler(commands=['studentscores'])
def student_scores(message):
    if message.from_user.id != ADMIN_USER_ID:
        bot.send_message(message.chat.id, "You are not authorized to use this command.")
        return

    try:
        _, student_name = message.text.split(' ', 1)

        # Fetch all scores for the student
        cursor.execute('SELECT test_code, part, score FROM student_results WHERE student_name = ?', (student_name,))
        results = cursor.fetchall()

        if not results:
            bot.send_message(message.chat.id, f"No scores found for {student_name}.")
            return

        # Format the scores
        response = f"Scores for {student_name}:\n"
        for test_code, part, score in results:
            response += f"Test '{test_code}' ({part}): {score} points\n"

        bot.send_message(message.chat.id, response)
    except ValueError:
        bot.send_message(message.chat.id, "Usage: /studentscores <name>")

# Command: Update Test (Restricted to Admin)
@bot.message_handler(commands=['updatetest'])
def update_test(message):
    if message.from_user.id != ADMIN_USER_ID:
        bot.send_message(message.chat.id, "You are not authorized to use this command.")
        return

    try:
        _, test_code, part, new_answer_key = message.text.split(' ', 3)
        part = part.lower()

        if part not in ["math", "english"]:
            raise ValueError("Part must be 'math' or 'english'.")

        # Check if the test part exists
        cursor.execute('SELECT answer_key FROM tests WHERE test_code = ? AND part = ?', (test_code, part))
        if not cursor.fetchone():
            bot.send_message(message.chat.id, f"Test '{test_code}' for part '{part}' not found.")
            return

        # Update the answer key
        if not execute_db_query('UPDATE tests SET answer_key = ? WHERE test_code = ? AND part = ?', 
                              (new_answer_key, test_code, part)):
            bot.send_message(message.chat.id, "Failed to update test. Please try again.")
            return

        bot.send_message(message.chat.id, f"Answer key for {part} part of test '{test_code}' has been updated successfully.")
    except ValueError as e:
        bot.send_message(message.chat.id, f"Error: {e}\nUsage: /updatetest <code> <part> <new_answer_key>")

# Command: Rankings
@bot.message_handler(commands=['rankings'])
def rankings(message):
    try:
        _, test_code = message.text.split(' ', 1)

        # Fetch all students who took both parts of the test
        cursor.execute('''
            SELECT student_name, SUM(score) as total_score 
            FROM student_results 
            WHERE test_code = ? 
            GROUP BY student_name 
            ORDER BY total_score DESC
        ''', (test_code,))
        results = cursor.fetchall()

        if not results:
            bot.send_message(message.chat.id, f"No results found for test '{test_code}'.")
            return

        # Format the rankings
        response = f"Rankings for test '{test_code}':\n"
        for rank, (student_name, total_score) in enumerate(results, start=1):
            response += f"{rank}. {student_name}: {total_score} points\n"

        bot.send_message(message.chat.id, response)
    except ValueError:
        bot.send_message(message.chat.id, "Usage: /rankings <test_code>")

# Command: Delete Submission (Restricted to Admin)
@bot.message_handler(commands=['deletesubmission'])
def delete_submission(message):
    if message.from_user.id != ADMIN_USER_ID:
        bot.send_message(message.chat.id, "You are not authorized to use this command.")
        return

    try:
        # Split the input into student_name, test_code, and part
        _, student_name, test_code, part = message.text.split(' ', 3)
        part = part.lower()

        if part not in ["math", "english"]:
            raise ValueError("Part must be 'math' or 'english'.")

        # Check if the submission exists
        cursor.execute('SELECT * FROM student_results WHERE student_name = ? AND test_code = ? AND part = ?', 
                      (student_name, test_code, part))
        if not cursor.fetchone():
            bot.send_message(message.chat.id, f"No submission found for {student_name} in test '{test_code}' ({part} part).")
            return

        # Delete the submission
        if not execute_db_query('DELETE FROM student_results WHERE student_name = ? AND test_code = ? AND part = ?', 
                              (student_name, test_code, part)):
            bot.send_message(message.chat.id, "Failed to delete submission. Please try again.")
            return

        bot.send_message(message.chat.id, f"Submission for {student_name} in test '{test_code}' ({part} part) has been deleted.")
    except ValueError as e:
        logger.error(f"Error in /deletesubmission: {e}")
        bot.send_message(message.chat.id, f"Error: {e}\nUsage: /deletesubmission <student_name> <test_code> <part>")
    except Exception as e:
        logger.error(f"Unexpected error in /deletesubmission: {e}")
        bot.send_message(message.chat.id, "Failed to delete submission. Please try again.")

# Handle Test Submission
@bot.message_handler(func=lambda message: '*' in message.text)
def check_test(message):
    try:
        student_name = message.from_user.username or message.from_user.first_name
        test_part_code, student_answers = message.text.split('*', 1)

        # Extract test code and part
        if '_' in test_part_code:
            test_code, part = test_part_code.rsplit('_', 1)
        else:
            bot.send_message(message.chat.id, "Invalid format. Use <test_code>_<part>*<answers>.")
            return

        if part.lower() not in ["math", "english"]:
            bot.send_message(message.chat.id, "Invalid part. Use 'math' or 'english'.")
            return

        # Normalize student answers
        student_answers = [answer.strip().lower() for answer in student_answers.split(',') if answer.strip()]
        logger.info(f"Student '{student_name}' submitted answers for {part} part: {student_answers}")

        # Check the number of answers
        expected_answers = 44 if part == "math" else 54
        actual_answers = len(student_answers)
        if actual_answers != expected_answers:
            bot.send_message(
                message.chat.id,
                f"You entered {actual_answers} answers, but the {part} part requires {expected_answers} answers.\n"
                "Please check and resubmit your answers."
            )
            return

        # Check for invalid answers (e.g., 'e' for English)
        invalid_answers = []
        for i, answer in enumerate(student_answers, start=1):
            if part == "english" and answer not in ["a", "b", "c", "d"]:
                invalid_answers.append(f"Q{i}: Invalid answer '{answer}'. Must be a, b, c, or d.")

        if invalid_answers:
            bot.send_message(
                message.chat.id,
                f"Invalid answers found:\n{'; '.join(invalid_answers)}\n"
                "Please correct your answers and resubmit."
            )
            return

        # Check if the student has already completed this part
        cursor.execute('SELECT * FROM student_results WHERE student_name = ? AND test_code = ? AND part = ?', 
                      (student_name, test_code, part))
        if cursor.fetchone():
            bot.send_message(message.chat.id, "You have already completed this test. Results are saved.")
            return

        # Fetch the answer key for the specified part
        cursor.execute('SELECT answer_key FROM tests WHERE test_code = ? AND part = ?', (test_code, part))
        result = cursor.fetchone()

        if not result:
            bot.send_message(message.chat.id, f"Test code '{test_code}' for part '{part}' not found.")
            return

        # Split the correct answers into groups (one group per question)
        correct_answers = result[0].split(';')

        # Compare student answers to correct answers
        correct_count = 0
        mistakes = []

        for i, (student_answer, correct_answer) in enumerate(zip(student_answers, correct_answers), start=1):
            try:
                # Normalize the correct answers (there may be multiple correct answers per question)
                correct_answers_list = [ans.strip().lower() for ans in correct_answer.split(',')]

                # Check if the student's answer matches any of the correct answers
                if student_answer in correct_answers_list:
                    correct_count += 1
                else:
                    mistakes.append(f"Q{i}: Correct={correct_answers_list}, Your={student_answer}")
            except Exception as e:
                logger.error(f"Error processing Q{i}: {e}")
                mistakes.append(f"Q{i}: Error parsing your answer '{student_answer}'")

        # Save the results
        score = correct_count
        mistakes_str = "\n".join(mistakes)  # This joins mistakes with a newline
        if not execute_db_query(
            'INSERT INTO student_results (student_name, test_code, part, student_answers, score, mistakes) VALUES (?, ?, ?, ?, ?, ?)',
            (student_name, test_code, part, ",".join(student_answers), score, mistakes_str)
        ):
            bot.send_message(message.chat.id, "Failed to save your results. Please try again.")
            return

        # Send the result to the student
        bot.send_message(
            message.chat.id,
            f"{part.capitalize()} part completed!\nScore: {score}/{len(correct_answers)}\nMistakes:\n{mistakes_str if mistakes else 'None'}"
        )

        # Check if both parts are completed and show overall results
        cursor.execute('SELECT part FROM student_results WHERE student_name = ? AND test_code = ?', 
                      (student_name, test_code))
        completed_parts = [row[0] for row in cursor.fetchall()]

        if set(completed_parts) == {"math", "english"}:
            # Calculate overall score
            cursor.execute('SELECT SUM(score) FROM student_results WHERE student_name = ? AND test_code = ?', 
                          (student_name, test_code))
            total_score = cursor.fetchone()[0]
            total_questions = 44 + 54  # Math (44) + English (54)

            bot.send_message(
                message.chat.id,
                f"Both parts completed!\nOverall Score: {total_score}/{total_questions}"
            )

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        bot.send_message(message.chat.id, "Error processing your test. Please check your input format.")

# Start the bot
bot.polling(none_stop=True)