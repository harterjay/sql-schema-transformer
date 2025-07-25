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
                left: 20px;
                z-index: 1000;
            }}
            </style>
            <div class="logo-container">
                <a href="mailto:support@riptonic.com" target="_blank">
                    <img src="data:image/png;base64,{get_image_base64("riptonic_grey_no_bg.png")}" 
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
                left: 20px;
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
        layout="centered",
        initial_sidebar_state="collapsed"
    )
    
    # Hide GitHub link and other elements
    st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .stDeployButton {display: none;}
    
    /* Center the main content */
    .main .block-container {
        max-width: 600px;
        margin: 0 auto;
        padding-top: 2rem;
    }
    
    /* Style the auth forms */
    .stForm {
        background-color: white;
        border-radius: 12px;
        padding: 2rem;
        box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        border: 1px solid #e9ecef;
    }
    
    /* Center the title */
    h1 {
        text-align: center;
        color: #2c3e50;
        margin-bottom: 2rem;
    }
    </style>
    """, unsafe_allow_html=True)
    
    show_riptonic_logo()
    
    if "auth_mode" not in st.session_state:
        st.session_state["auth_mode"] = None

    if st.session_state["auth_mode"] is None:
        st.markdown("""
        <div style="text-align: center; padding: 2rem 0;">
            <h1 style="color: #2c3e50; margin-bottom: 1rem;">SQL Schema Transformer</h1>
            <p style="color: #6c757d; margin-bottom: 2rem;">Sign in to access your account</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Create a centered container for the buttons (no card)
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("🔐 Login", use_container_width=True):
                    st.session_state["auth_mode"] = "login"
                    st.rerun()
            with col_b:
                if st.button("📝 Sign Up", use_container_width=True):
                    st.session_state["auth_mode"] = "signup"
                    st.rerun()
        st.stop()

    if st.session_state["auth_mode"] == "login":
        st.markdown("""
        <div style="text-align: center; padding: 2rem 0;">
            <h1 style="color: #2c3e50; margin-bottom: 1rem;">Welcome Back</h1>
            <p style="color: #6c757d; margin-bottom: 2rem;">Sign in to your account</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Center the login form
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.form("login_form"):
                email = st.text_input("📧 Email", placeholder="Enter your email")
                password = st.text_input("🔒 Password", type="password", placeholder="Enter your password")
                login = st.form_submit_button("🔐 Login", use_container_width=True)
                if login:
                    if not email or not password:
                        st.error("Please enter both email and password.")
                    else:
                        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                        if hasattr(res, 'user') and res.user:
                            st.session_state["user"] = res.user
                            fetch_user_status(res.user)
                            st.success("✅ Login successful!")
                            st.session_state["auth_mode"] = None
                            st.rerun()
                        else:
                            st.error("❌ Login failed. Please check your credentials.")
            
            if st.button("← Back", use_container_width=True):
                st.session_state["auth_mode"] = None
                st.rerun()

    if st.session_state["auth_mode"] == "signup":
        st.markdown("""
        <div style="text-align: center; padding: 2rem 0;">
            <h1 style="color: #2c3e50; margin-bottom: 1rem;">Create Account</h1>
            <p style="color: #6c757d; margin-bottom: 2rem;">Join SQL Schema Transformer</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Center the signup form
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            with st.form("signup_form"):
                email = st.text_input("📧 Email", placeholder="Enter your email")
                password = st.text_input("🔒 Password", type="password", placeholder="Create a password")
                confirm_password = st.text_input("🔒 Confirm Password", type="password", placeholder="Confirm your password")
                signup = st.form_submit_button("📝 Sign Up", use_container_width=True)
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
                            st.success("✅ Account created! Please check your email to confirm your account.")
                            st.session_state["auth_mode"] = "login"
                            st.rerun()
                        else:
                            st.error("❌ Signup failed. Email may already be registered.")
            
            if st.button("← Back", use_container_width=True):
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

# Enhanced sidebar styling
st.sidebar.markdown("""
<div style="background-color: #1f77b4; padding: 1rem; border-radius: 8px; margin-bottom: 1rem;">
    <h3 style="color: white; margin: 0; text-align: center;">Navigation</h3>
</div>
""", unsafe_allow_html=True)

# Show user info with Pro indicator in sidebar
if st.session_state["user"]:
    user_email = st.session_state["user"].email
    if is_paid:
        st.sidebar.markdown(f"""
        <div style="background-color: #fff3cd; border: 1px solid #ffeaa7; border-radius: 8px; padding: 0.75rem; margin-bottom: 1rem;">
            <p style="margin: 0; color: #856404; font-weight: 600;">👤 {user_email}</p>
            <p style="margin: 0.25rem 0 0 0; color: #856404; font-size: 0.9rem;">⭐ PRO Member</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.sidebar.markdown(f"""
        <div style="background-color: #e3f2fd; border: 1px solid #bbdefb; border-radius: 8px; padding: 0.75rem; margin-bottom: 1rem;">
            <p style="margin: 0; color: #1976d2; font-weight: 600;">👤 {user_email}</p>
            <p style="margin: 0.25rem 0 0 0; color: #1976d2; font-size: 0.9rem;">Free Account</p>
        </div>
        """, unsafe_allow_html=True)

# Check if user is admin
user_email = st.session_state["user"].email.strip().lower()
admin_emails_normalized = [e.strip().lower() for e in admin_emails]
is_admin = user_email in admin_emails_normalized

# Main app (always visible)
if st.sidebar.button("🗄️ SQL Transform", use_container_width=True):
    st.session_state["current_page"] = "main"

# Account (always visible)
if st.sidebar.button("👤 Account", use_container_width=True):
    st.session_state["current_page"] = "account"

# Admin tools (only for admins)
if is_admin:
    st.sidebar.markdown("---")
    st.sidebar.markdown("""
    <div style="background-color: #f8f9fa; padding: 0.5rem; border-radius: 6px; margin: 0.5rem 0;">
        <p style="margin: 0; color: #6c757d; font-weight: 600; font-size: 0.9rem;">🔧 Admin Tools</p>
    </div>
    """, unsafe_allow_html=True)
    
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

if st.session_state["current_page"] == "analytics":
    user_email = st.session_state["user"].email.strip().lower()
    admin_emails_normalized = [e.strip().lower() for e in admin_emails]
    if user_email in admin_emails_normalized:
        show_analytics()
    else:
        st.warning("You do not have access to this page.")
    st.stop()

if st.session_state["current_page"] == "improvements":
    user_email = st.session_state["user"].email.strip().lower()
    admin_emails_normalized = [e.strip().lower() for e in admin_emails]
    if user_email in admin_emails_normalized:
        show_improvements()
    else:
        st.warning("You do not have access to this page.")
    st.stop()

if st.session_state["current_page"] == "account":
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

# Modern CSS styling for professional look
st.markdown("""
<style>
/* Hide default Streamlit elements */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}
.stDeployButton {display: none;}

/* Modern color scheme and typography */
:root {
    --primary-color: #1f77b4;
    --secondary-color: #ff7f0e;
    --success-color: #2ca02c;
    --warning-color: #d62728;
    --text-color: #2c3e50;
    --background-color: #f8f9fa;
    --card-background: #ffffff;
    --border-color: #e9ecef;
}

/* Global styles */
.stApp {
    background-color: var(--background-color);
}

/* Enhanced sidebar styling */
.sidebar .sidebar-content {
    background-color: var(--card-background);
    border-right: 1px solid var(--border-color);
}

/* Modern button styling */
.stButton > button {
    background-color: var(--primary-color);
    color: white;
    border: none;
    border-radius: 8px;
    padding: 12px 24px;
    font-weight: 600;
    transition: all 0.3s ease;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.stButton > button:hover {
    background-color: #1565c0;
    transform: translateY(-1px);
    box-shadow: 0 4px 8px rgba(0,0,0,0.15);
}

/* Enhanced form styling */
.stForm {
    background-color: var(--card-background);
    border-radius: 12px;
    padding: 24px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    border: 1px solid var(--border-color);
}

/* File uploader styling */
.stFileUploader {
    border: 2px dashed var(--border-color);
    border-radius: 8px;
    padding: 20px;
    text-align: center;
    transition: border-color 0.3s ease;
}

.stFileUploader:hover {
    border-color: var(--primary-color);
}

/* Enhanced text styling */
h1, h2, h3 {
    color: var(--text-color);
    font-weight: 700;
}

/* Success/Error message styling */
.stAlert {
    border-radius: 8px;
    border: none;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

/* Code block styling */
.stCodeBlock {
    background-color: #f8f9fa;
    border-radius: 8px;
    border: 1px solid var(--border-color);
}

/* Radio button styling */
.stRadio > label {
    background-color: var(--card-background);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 12px 16px;
    margin: 4px 0;
    transition: all 0.3s ease;
}

.stRadio > label:hover {
    border-color: var(--primary-color);
    background-color: #f0f8ff;
}

/* Text input styling */
.stTextInput > div > div > input {
    border-radius: 8px;
    border: 1px solid var(--border-color);
    padding: 12px 16px;
    transition: border-color 0.3s ease;
}

.stTextInput > div > div > input:focus {
    border-color: var(--primary-color);
    box-shadow: 0 0 0 2px rgba(31, 119, 180, 0.2);
}

/* Sidebar button enhancements */
.sidebar .stButton > button {
    width: 100%;
    margin: 4px 0;
    border-radius: 8px;
    font-size: 14px;
}

/* Logo container enhancement */
.logo-container {
    position: fixed;
    bottom: 20px;
    left: 20px;
    z-index: 1000;
    background-color: rgba(255, 255, 255, 0.9);
    border-radius: 8px;
    padding: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
}
</style>
""", unsafe_allow_html=True)

# Show Riptonic logo at bottom right of all pages
show_riptonic_logo()

# Header with modern styling
st.markdown("""
<div style="text-align: center; padding: 2rem 0; background-color: #1f77b4; border-radius: 12px; margin-bottom: 2rem;">
    <h1 style="color: white; margin: 0; font-size: 2.5rem; font-weight: 700;">SQL Schema Transformer</h1>
    <p style="color: rgba(255,255,255,0.9); margin: 0.5rem 0 0 0; font-size: 1.1rem;">Transform your database schemas with AI-powered SQL generation</p>
</div>
""", unsafe_allow_html=True)

# Main description with better formatting
st.markdown("""
<div style="background-color: white; padding: 1.5rem; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin-bottom: 2rem;">
    <h3 style="color: #2c3e50; margin-top: 0;">📋 How it works</h3>
    <p style="color: #555; line-height: 1.6; margin-bottom: 1rem;">
        Upload your source and target schema Excel files. The app will generate a SQL SELECT statement to transform and join the source schemas to produce the target schema (formatted for Microsoft SQL Server).
    </p>
    <div style="background-color: #f8f9fa; padding: 1rem; border-radius: 8px; border-left: 4px solid #1f77b4;">
        <p style="margin: 0; color: #2c3e50; font-weight: 600;">📄 Required Excel columns:</p>
        <p style="margin: 0.5rem 0 0 0; color: #555;"><code>table</code>, <code>column</code>, <code>type</code>, <code>description</code></p>
    </div>
    <p style="color: #555; margin-top: 1rem; margin-bottom: 0;">
        You may upload multiple source files (e.g., transactional, master data, etc.). Optionally, you can upload a Join Key table (Excel) with columns: <code>left_table</code>, <code>left_field</code>, <code>right_table</code>, <code>right_field</code> to specify join relationships.
    </p>
</div>
""", unsafe_allow_html=True)

# Enhanced form section - very compact
st.markdown("""
<div style="background-color: white; padding: .5rem; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); margin-bottom: .5rem;">
    <h3 style="color: #2c3e50; margin-top: 0; margin-bottom: 0.1rem;">⚙️ Configuration</h3>
""", unsafe_allow_html=True)

# Unmapped fields option with better styling
st.markdown("**🔧 Unmapped Fields Handling**")
unmapped_option = st.radio(
    "What should the SQL output for unmapped fields?",
    ("Null", "NO_VALUE", "Custom value"),
    help="Choose how to handle target fields that don't have a corresponding source field"
)
custom_value = ""
if unmapped_option == "Custom value":
    custom_value = st.text_input("Enter custom value (max 10 characters):", max_chars=10, help="This value will be used for all unmapped fields")

st.markdown("</div>", unsafe_allow_html=True)

# File upload section with enhanced styling - very compact
st.markdown("""
<div style="background-color: white; padding: 1rem; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); margin-bottom: 1rem;">
    <h3 style="color: #2c3e50; margin-top: 0; margin-bottom: 0.5rem;">📁 File Upload</h3>
""", unsafe_allow_html=True)

with st.form("schema_form"):
    # Create columns for better layout
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("**📊 Source Schemas**")
        # Enforce source file limit for free users
        if not is_paid:
            st.info("💡 Free users can only upload 1 source file. Upgrade for unlimited access!")
            source_files = st.file_uploader("Source schema Excel files (1 file for free users)", type=["xlsx"], accept_multiple_files=False, help="Upload your source schema Excel files")
        else:
            source_files = st.file_uploader("Source schema Excel files (you can select multiple)", type=["xlsx"], accept_multiple_files=True, help="Upload your source schema Excel files")
    
    with col2:
        st.markdown("**🎯 Target Schema**")
        target_file = st.file_uploader("Target schema Excel file", type=["xlsx"], help="Upload your target schema Excel file")
    
    st.markdown("**🔗 Join Keys (Optional)**")
    join_key_file = st.file_uploader("Join Key table (Excel, columns: left_table, left_field, right_table, right_field)", type=["xlsx"], help="Specify join relationships between tables")
    
    # Enhanced submit button
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        submitted = st.form_submit_button("🚀 Generate SQL", use_container_width=True)

st.markdown("</div>", unsafe_allow_html=True)

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
            with st.spinner("🤖 Generating SQL with Claude..."):
                sql = call_claude(prompt)
            
            # Enhanced results display
            st.markdown("""
            <div style="background-color: #f8f9fa; padding: 1rem; border-radius: 8px; margin: 1rem 0;">
                <h4 style="color: #2c3e50; margin: 0 0 0.5rem 0;">✅ SQL Generated Successfully!</h4>
                <p style="color: #555; margin: 0;">Your SQL transformation query is ready below.</p>
            </div>
            """, unsafe_allow_html=True)
            
            # Enhanced code block
            st.markdown("**📋 Generated SQL Query:**")
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

