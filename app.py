import streamlit as st
import pandas as pd
import os
import httpx
from dotenv import load_dotenv
from supabase import create_client, Client
from io import BytesIO
import stripe

stripe.api_key = st.secrets["STRIPE_SECRET_KEY"]

# Load environment variables
load_dotenv()

# --- Supabase Setup ---
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Helper functions (moved to top) ---
def parse_schema(file) -> pd.DataFrame:
    """Parse an Excel schema file and return a DataFrame."""
    try:
        # If file is bytes, wrap in BytesIO
        if isinstance(file, bytes):
            file = BytesIO(file)
        # st.write("File object type:", type(file))
        # st.write("File name:", getattr(file, 'name', None))
        if hasattr(file, 'getvalue'):
            pass
            # st.write("First 20 bytes:", file.getvalue()[:20])
        file.seek(0)
        df = pd.read_excel(file)
    except Exception as e:
        # st.write("Exception details:", str(e))
        raise ValueError("The uploaded file is not a valid Excel (.xlsx) file. Please check your file and try again.") from e
    df.columns = [c.lower() for c in df.columns]
    required_cols = {"table", "column", "type", "description"}
    if not required_cols.issubset(df.columns):
        raise ValueError("Missing required columns in schema file.")
    return df

def schema_to_text(df: pd.DataFrame, source_name: str | None = None) -> str:
    """Convert schema DataFrame to text format."""
    prefix = f"[{source_name}]\n" if source_name else ""
    return prefix + "\n".join(
        f"{row['table']}.{row['column']} {row['type']} -- {row['description']}"
        for _, row in df.iterrows()
    )

def join_keys_to_text(df: pd.DataFrame) -> str:
    """Convert join keys DataFrame to text format."""
    # Assume columns: left_table, left_field, right_table, right_field
    return "\n".join(
        f"{row['left_table']}.{row['left_field']} = {row['right_table']}.{row['right_field']}" for _, row in df.iterrows()
    )

def call_claude(prompt: str) -> str:
    """Call Claude API to generate SQL based on the prompt."""
    # Environment variable loaded from .env file
    CLAUDE_API_KEY: str = os.getenv("CLAUDE_API_KEY") or ""
    if not CLAUDE_API_KEY:
        raise ValueError("CLAUDE_API_KEY environment variable not found. Please create a .env file with your Claude API key.")
    
    CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    data = {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 4096,  # or higher, if supported
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    response = httpx.post(CLAUDE_API_URL, headers=headers, json=data, timeout=60)
    response.raise_for_status()
    response_data = response.json()
    return response_data["content"][0]["text"]

def show_riptonic_logo():
    """Display Riptonic logo as a clickable link to support email at bottom right."""
    try:
        # Use CSS to position logo at bottom right
        st.markdown(
            f'''
            <style>
            .logo-container {{
                position: fixed;
                bottom: 20px;
                right: 20px;
                z-index: 1000;
            }}
            </style>
            <div class="logo-container">
                <a href="mailto:support@riptonic.com" target="_blank">
                    <img src="data:image/png;base64,{get_image_base64("riptonic_grey.png")}" 
                    width="150" style="display: block;">
                </a>
            </div>
            ''',
            unsafe_allow_html=True
        )
    except Exception as e:
        # Fallback: just show text link at bottom right
        st.markdown(
            f'''
            <style>
            .logo-container {{
                position: fixed;
                bottom: 20px;
                right: 20px;
                z-index: 1000;
            }}
            </style>
            <div class="logo-container">
                <a href="mailto:support@riptonic.com" target="_blank">
                    <p style="text-align: center; font-size: 12px; color: #666;">Riptonic Support</p>
                </a>
            </div>
            ''',
            unsafe_allow_html=True
        )

def get_image_base64(image_path):
    """Get base64 encoded image for embedding in HTML."""
    try:
        import base64
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode()
    except:
        return ""

# --- Auth Helpers ---
if "user" not in st.session_state:
    st.session_state["user"] = None

# --- Freemium Logic Helpers ---
def insert_user_if_new(user):
    # Insert user into 'users' table if not exists
    res = supabase.table("users").select("id").eq("id", user.id).execute()
    if not res.data:
        supabase.table("users").insert({
            "id": user.id,
            "email": user.email,
            "is_paid": False
        }).execute()

def fetch_user_status(user):
    res = supabase.table("users").select("is_paid, signup_date").eq("id", user.id).single().execute()
    if res.data:
        st.session_state["is_paid"] = res.data["is_paid"]
        st.session_state["signup_date"] = pd.to_datetime(res.data["signup_date"])
    else:
        st.session_state["is_paid"] = False
        st.session_state["signup_date"] = pd.Timestamp.now()

def get_sql_generations_today(user):
    today = pd.Timestamp.now().date()
    res = supabase.table("usage_logs").select("timestamp").eq("user_id", user.id).eq("action", "generate_sql").execute()
    if not res.data:
        return 0
    df = pd.DataFrame(res.data)
    df["date"] = pd.to_datetime(df["timestamp"]).dt.date
    return (df["date"] == today).sum()

def get_trial_days_left(signup_date):
    days_used = (pd.Timestamp.now().date() - signup_date.date()).days
    return max(0, 10 - days_used)

def create_checkout_session(user_email):
    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price': st.secrets["STRIPE_PRICE_ID"],
            'quantity': 1,
        }],
        mode='subscription',
        customer_email=user_email,
        success_url=f'https://sql-schema-transformer-cwjjqe7eonrs2qsi96bn2u.streamlit.app?session_id={{CHECKOUT_SESSION_ID}}&email={user_email}',
        cancel_url='https://sql-schema-transformer-cwjjqe7eonrs2qsi96bn2u.streamlit.app',
    )
    return session.url

# --- Update show_login to insert user on signup and fetch status on login ---
def show_login():
    # Set page config for login page
    st.set_page_config(
        page_title="SQL Schema Transformer - Login", 
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Hide GitHub link and other elements
    st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stDeployButton {display: none;}
    </style>
    """, unsafe_allow_html=True)
    
    show_riptonic_logo()
    
    if "auth_mode" not in st.session_state:
        st.session_state["auth_mode"] = None

    if st.session_state["auth_mode"] is None:
        st.title("SQL Schema Transformer")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Login"):
                st.session_state["auth_mode"] = "login"
                st.rerun()
        with col2:
            if st.button("Sign Up"):
                st.session_state["auth_mode"] = "signup"
                st.rerun()
        st.stop()

    if st.session_state["auth_mode"] == "login":
        st.title("SQL Schema Transformer")
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            login = st.form_submit_button("Login")
            if login:
                if not email or not password:
                    st.error("Please enter both email and password.")
                else:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    if hasattr(res, 'user') and res.user:
                        st.session_state["user"] = res.user
                        fetch_user_status(res.user)
                        st.success("Logged in!")
                        st.session_state["auth_mode"] = None
                        st.rerun()
                    else:
                        st.error("Login failed. Please check your credentials.")
        if st.button("Back"):
            st.session_state["auth_mode"] = None
            st.rerun()

    if st.session_state["auth_mode"] == "signup":
        st.title("SQL Schema Transformer")
        with st.form("signup_form"):
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            confirm_password = st.text_input("Confirm Password", type="password")
            signup = st.form_submit_button("Sign Up")
            if signup:
                if not email or not password or not confirm_password:
                    st.error("Please fill in all fields.")
                elif password != confirm_password:
                    st.error("Passwords do not match.")
                else:
                    res = supabase.auth.sign_up({"email": email, "password": password})
                    if hasattr(res, 'user') and res.user:
                        insert_user_if_new(res.user)
                        fetch_user_status(res.user)
                        st.success("Check your email to confirm your account.")
                        st.session_state["auth_mode"] = "login"
                        st.rerun()
                    else:
                        st.error("Signup failed. Email may already be registered.")
        if st.button("Back"):
            st.session_state["auth_mode"] = None
            st.rerun()

def show_logout():
    if st.button("Logout"):
        st.session_state["user"] = None
        st.rerun()

# Admin emails for analytics access
admin_emails = ["harterjay@gmail.com"]  # Replace with your email

def get_usage_stats():
    res = supabase.table("usage_logs").select("*").execute()
    df = pd.DataFrame(res.data)
    return df

def show_analytics():
    # Set page config for analytics page
    st.set_page_config(
        page_title="SQL Schema Transformer - Analytics", 
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Hide GitHub link and other elements
    st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stDeployButton {display: none;}
    </style>
    """, unsafe_allow_html=True)
    
    st.header("Usage Analytics")
    df = get_usage_stats()
    if df.empty:
        st.info("No usage data yet.")
        return
    st.write("All usage logs:", df)
    st.write("SQL generations per user:")
    st.bar_chart(df.groupby("email").size())
    st.write("SQL generations over time:")
    df['date'] = pd.to_datetime(df['timestamp']).dt.date
    st.line_chart(df.groupby('date').size())
    


def show_account():
    # Set page config for account page
    st.set_page_config(
        page_title="SQL Schema Transformer - Account", 
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Hide GitHub link and other elements
    st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stDeployButton {display: none;}
    </style>
    """, unsafe_allow_html=True)
    
    st.header("Account Settings")
    
    user = st.session_state["user"]
    user_email = user.email
    
    # Account Information
    st.subheader("Account Information")
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**Email:** {user_email}")
        st.write(f"**Member since:** {signup_date.strftime('%B %d, %Y')}")
    
    with col2:
        if is_paid:
            st.markdown(f"**Tier:** <span style='color: black; font-weight: bold;'>PRO ⭐⭐⭐</span>", unsafe_allow_html=True)
            # Get next billing date (approximate - monthly subscription)
            next_billing = signup_date + pd.DateOffset(months=1)
            st.write(f"**Next billing:** {next_billing.strftime('%B %d, %Y')}")
        else:
            st.write("**Tier:** Free")
            st.write(f"**Trial ends:** {(signup_date + pd.DateOffset(days=10)).strftime('%B %d, %Y')}")
    
    st.markdown("---")
    
    # Subscription Management
    st.subheader("Subscription Management")
    
    if is_paid:
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Manage Subscription", type="secondary"):
                st.info("Contact support@riptonic.com to manage your subscription.")
        
        with col2:
            if st.button("Cancel Subscription", type="secondary"):
                st.warning("Contact support@riptonic.com to cancel your subscription.")
    else:
        st.write("Upgrade to Pro for unlimited access!")
        checkout_url = create_checkout_session(user_email)
        st.link_button("Upgrade to Pro", checkout_url)
    
    st.markdown("---")
    
    # Password Change
    st.subheader("Change Password")
    with st.form("change_password_form"):
        current_password = st.text_input("Current Password", type="password")
        new_password = st.text_input("New Password", type="password")
        confirm_password = st.text_input("Confirm New Password", type="password")
        submitted = st.form_submit_button("Change Password")
        
        if submitted:
            if not current_password or not new_password or not confirm_password:
                st.error("Please fill in all fields.")
            elif new_password != confirm_password:
                st.error("New passwords do not match.")
            else:
                try:
                    # Update password in Supabase
                    supabase.auth.update_user({"password": new_password})
                    st.success("Password updated successfully!")
                except Exception as e:
                    st.error(f"Error updating password: {e}")
    
    st.markdown("---")
    
    # Usage Statistics
    st.subheader("Usage Statistics")
    generations_today = get_sql_generations_today(user)
    if is_paid:
        st.write(f"**SQL generations today:** {generations_today} (unlimited)")
    else:
        st.write(f"**SQL generations today:** {generations_today}/2")
        trial_days_left = get_trial_days_left(signup_date)
        st.write(f"**Trial days remaining:** {trial_days_left}")

def show_improvements():
    # Set page config for improvements page
    st.set_page_config(
        page_title="SQL Schema Transformer - Improvements", 
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Hide GitHub link and other elements
    st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stDeployButton {display: none;}
    </style>
    """, unsafe_allow_html=True)
    
    st.header("Future Improvements")
    
    # Add new improvement form
    with st.form("add_improvement_form", clear_on_submit=True):
        name = st.text_input("Improvement Name")
        description = st.text_area("Description")
        submitted = st.form_submit_button("Add Improvement Idea")
        if submitted:
            if not name:
                st.error("Name is required.")
            else:
                supabase.table("improvements").insert({
                    "name": name,
                    "description": description,
                }).execute()
                st.success("Improvement idea added!")
                st.rerun()
    
    # List all improvements
    res = supabase.table("improvements").select("*").order("date_entered", desc=True).execute()
    df = pd.DataFrame(res.data)
    if not df.empty:
        # Show read-only table for overview
        st.subheader("Overview")
        display_df = df.rename(columns={"date_entered": "Date Entered"})
        st.dataframe(
            display_df[["name", "description", "status", "Date Entered"]],
            use_container_width=True,
            key="improvements_overview"
        )
        
        # Edit button to toggle edit mode
        if st.button("Edit Improvements", type="secondary"):
            st.session_state["show_edit_mode"] = True
        
        # Show edit section only when button is clicked
        if st.session_state.get("show_edit_mode", False):
            st.subheader("Edit Improvements")
            
            # Create editable form for each improvement
            for idx, row in df.iterrows():
                with st.expander(f"Edit: {row['name']}", expanded=False):
                    with st.form(f"edit_form_{row['id']}", clear_on_submit=False):
                        edited_name = st.text_input("Name", value=row['name'], key=f"name_{row['id']}")
                        edited_description = st.text_area("Description", value=row['description'], key=f"desc_{row['id']}")
                        # Handle status safely
                        status_options = ["pending", "in_progress", "completed"]
                        current_status = row.get('status', 'pending')
                        if current_status is None or current_status not in status_options:
                            current_status = 'pending'
                        status_index = status_options.index(current_status)
                        
                        edited_status = st.selectbox("Status", status_options, 
                                                   index=status_index,
                                                   key=f"status_{row['id']}")
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.form_submit_button("Update"):
                                supabase.table("improvements").update({
                                    "name": edited_name,
                                    "description": edited_description,
                                    "status": edited_status
                                }).eq("id", row['id']).execute()
                                st.success("Updated!")
                                st.rerun()
                        
                        with col2:
                            if st.form_submit_button("Delete", type="secondary"):
                                supabase.table("improvements").delete().eq("id", row['id']).execute()
                                st.success("Deleted!")
                                st.rerun()
            
            # Button to hide edit mode
            if st.button("Hide Edit Mode", type="primary"):
                st.session_state["show_edit_mode"] = False
                st.rerun()
    else:
        st.info("No improvement ideas yet.")
    


# --- Page Routing ---
# --- After login, enforce freemium limits before showing main app ---
if not st.session_state["user"]:
    show_login()
    st.stop()

fetch_user_status(st.session_state["user"])

is_paid = st.session_state.get("is_paid", False)
signup_date = st.session_state.get("signup_date", pd.Timestamp.now())
trial_days_left = get_trial_days_left(signup_date)
generations_today = get_sql_generations_today(st.session_state["user"])

# Show user info with Pro indicator in sidebar
if st.session_state["user"]:
    user_email = st.session_state["user"].email
    if is_paid:
        st.sidebar.markdown(f"**Logged in as:** {user_email} <span style='color: black; font-weight: bold;'>PRO</span> ⭐⭐⭐", unsafe_allow_html=True)
    else:
        st.sidebar.markdown(f"**Logged in as:** {user_email}")

# Add sidebar navigation
st.sidebar.title("Navigation")

# Check if user is admin
user_email = st.session_state["user"].email.strip().lower()
admin_emails_normalized = [e.strip().lower() for e in admin_emails]
is_admin = user_email in admin_emails_normalized

# Main app (always visible)
if st.sidebar.button("🏠 Main App", use_container_width=True):
    st.session_state["current_page"] = "main"

# Account (always visible)
if st.sidebar.button("👤 Account", use_container_width=True):
    st.session_state["current_page"] = "account"

# Admin tools (only for admins)
if is_admin:
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Admin Tools**")
    
    if st.sidebar.button("📊 Usage Analytics", use_container_width=True):
        st.session_state["current_page"] = "analytics"
    
    if st.sidebar.button("💡 Future Improvements", use_container_width=True):
        st.session_state["current_page"] = "improvements"

# Initialize current page if not set
if "current_page" not in st.session_state:
    st.session_state["current_page"] = "main"

# Show usage/trial info and upgrade button for free users
if not is_paid:
    st.info(f"Trial days left: {trial_days_left} | SQL generations today: {generations_today}/2 | Upgrade for unlimited access!")
    checkout_url = create_checkout_session(st.session_state["user"].email)
    st.link_button("Upgrade to Pro", checkout_url)
    if trial_days_left == 0:
        st.error("Your 10-day trial has expired. Please upgrade to continue using the app.")
        st.stop()
    if generations_today >= 2:
        st.error("You have reached your daily limit of 2 SQL generations. Please try again tomorrow or upgrade for unlimited access.")
        st.stop()

if page == "Usage Analytics":
    user_email = st.session_state["user"].email.strip().lower()
    admin_emails_normalized = [e.strip().lower() for e in admin_emails]
    if user_email in admin_emails_normalized:
        show_analytics()
    else:
        st.warning("You do not have access to this page.")
    st.stop()

if page == "Future Improvements":
    user_email = st.session_state["user"].email.strip().lower()
    admin_emails_normalized = [e.strip().lower() for e in admin_emails]
    if user_email in admin_emails_normalized:
        show_improvements()
    else:
        st.warning("You do not have access to this page.")
    st.stop()

if page == "Account":
    show_account()
    st.stop()

# After login, add this to handle Stripe payment success
params = st.query_params
if "session_id" in params and "email" in params:
    session_id = params["session_id"][0]
    email = params["email"][0]
    try:
        session = stripe.checkout.Session.retrieve(session_id)
        if session.payment_status == "paid":
            supabase.table("users").update({"is_paid": True}).eq("email", email).execute()
            st.success("Payment successful! You are now a Pro user.")
            st.rerun()
    except Exception as e:
        st.error(f"Error verifying payment: {e}")

# --- Streamlit UI ---
st.set_page_config(
    page_title="SQL Schema Transformer", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Hide GitHub link in top right
st.markdown("""
<style>
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
.stDeployButton {display: none;}
</style>
""", unsafe_allow_html=True)

# Show Riptonic logo at bottom right of all pages
show_riptonic_logo()

st.title("SQL Schema Transformer")
st.write("Upload your source and target schema Excel files. The app will generate a SQL SELECT statement to transform and join the source schemas to produce the target schema (formatted for Microsoft SQL Server).\n\n**Excel files must have columns:** `table`, `column`, `type`, `description`. You may upload multiple source files (e.g., transactional, master data, etc.). Optionally, you can upload a Join Key table (Excel) with columns: `left_table`, `left_field`, `right_table`, `right_field` to specify join relationships.")

# Place these before the form
unmapped_option = st.radio(
    "What should the SQL output for unmapped fields?",
    ("Null", "NO_VALUE", "Custom value")
)
custom_value = ""
if unmapped_option == "Custom value":
    custom_value = st.text_input("Enter custom value (max 10 characters):", max_chars=10)

with st.form("schema_form"):
    # Enforce source file limit for free users
    if not is_paid:
        st.caption("Free users can only upload 1 source file. Upgrade for more.")
        source_files = st.file_uploader("Source schema Excel files (1 file for free users)", type=["xlsx"], accept_multiple_files=False)
    else:
        source_files = st.file_uploader("Source schema Excel files (you can select multiple)", type=["xlsx"], accept_multiple_files=True)
    target_file = st.file_uploader("Target schema Excel file", type=["xlsx"])
    join_key_file = st.file_uploader("(Optional) Join Key table (Excel, columns: left_table, left_field, right_table, right_field)", type=["xlsx"])
    submitted = st.form_submit_button("Generate SQL")

if submitted:
    if not source_files:
        st.error("Please upload at least one source schema file.")
        st.stop()
    if not target_file:
        st.error("Please upload a target schema file.")
        st.stop()
    else:
        try:
            # Parse all source files and keep their names
            source_schemas = []
            if isinstance(source_files, list):
                for file in source_files:
                    df = parse_schema(file)
                    source_schemas.append((file.name, df))
            else:
                df = parse_schema(source_files)
                source_schemas.append(("source_file", df))
            target_df = parse_schema(target_file)
            # Build source schemas text
            sources_text = "\n\n".join(
                schema_to_text(df, source_name=name) for name, df in source_schemas
            )
            target_text = schema_to_text(target_df)
            join_keys_text = ""
            if join_key_file:
                join_keys_df = pd.read_excel(join_key_file)
                # Validate columns
                required_join_cols = {"left_table", "left_field", "right_table", "right_field"}
                join_keys_df.columns = [c.lower() for c in join_keys_df.columns]
                if not required_join_cols.issubset(join_keys_df.columns):
                    raise ValueError("Join Key table must have columns: left_table, left_field, right_table, right_field")
                join_keys_text = join_keys_to_text(join_keys_df)
            # Build prompt
            if unmapped_option == "Null":
                unmapped_instruction = "If a target field cannot be mapped to any source field, output NULL for that field in the SELECT statement."
            elif unmapped_option == "NO_VALUE":
                unmapped_instruction = "If a target field cannot be mapped to any source field, output the string literal 'NO_VALUE' for that field in the SELECT statement."
            else:
                unmapped_instruction = f"If a target field cannot be mapped to any source field, output the string literal '{custom_value}' for that field in the SELECT statement."
            prompt = f"""Given the following source schemas (from different systems):\n{sources_text}\n\nAnd the following target schema:\n<target>\n{target_text}\n</target>\n"""
            if join_keys_text:
                prompt += f"\nUse the following join keys when joining tables (these are the correct join relationships):\n{join_keys_text}\n"
            prompt += f"\n{unmapped_instruction}\n"
            prompt += """
Write ONLY the SQL SELECT statement (no explanation, no comments, no description) that transforms and joins the appropriate source tables to produce the target schema. Use field names and descriptions to determine which source table/column to use for each target field. Format the SQL as a valid Microsoft SQL Server (T-SQL) script, using proper indentation, line breaks, and JOINs as needed. Do not include any explanation or commentary—output only the SQL code."""
            with st.spinner("Generating SQL with Claude..."):
                sql = call_claude(prompt)
            st.success("SQL generated!")
            st.code(sql, language="sql")
            # After successful SQL generation
            user = st.session_state["user"]
            if isinstance(source_files, list):
                num_source_files = len(source_files)
            else:
                num_source_files = 1 if source_files else 0
            supabase.table("usage_logs").insert({
                "user_id": user.id,
                "email": user.email,
                "action": "generate_sql",
                "details": {
                    "num_source_files": num_source_files,
                    "target_fields": len(target_df.columns),
                    # Add more details as needed
                }
            }).execute()
        except Exception as e:
            st.error(f"Error: {e}")

