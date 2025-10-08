# Copyright (C) 2025 code-zm
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import json
import os
import argparse
import math
import re
import getpass
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import requests
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

console = Console()

# Create data directory
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

def login():
    """Log in to NSA Codebreaker using environment variables or prompts"""
    console.print("[dim]Logging in to NSA Codebreaker...[/dim]")

    # Get credentials from environment variables or prompt
    email = os.environ.get('CBC_EMAIL')
    password = os.environ.get('CBC_PASSWORD')

    if not email:
        email = input("Email: ")

    if not password:
        password = getpass.getpass("Password: ")

    # Create session
    session = requests.Session()

    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
    }

    # Get home page or leaderboard to extract CSRF token (same as leaderboard scraper)
    response = session.get('https://nsa-codebreaker.org/leaderboard', headers=headers)
    response.raise_for_status()

    # Extract CSRF token from JavaScript (same pattern as leaderboard scraper)
    csrf_match = re.search(r'xhr\.setRequestHeader\(["\']X-CSRFToken["\']\s*,\s*["\']([^"\']+)["\']\)', response.text)
    if not csrf_match:
        raise ValueError("Could not find CSRF token")

    csrf_token = csrf_match.group(1)
    console.print(f"[dim]CSRF token: {csrf_token[:20]}...[/dim]")

    # POST login credentials
    login_data = {
        'email': email,
        'password': password,
        'csrf_token': csrf_token,
        'next': '',
        'submit': 'Login'
    }

    response = session.post('https://nsa-codebreaker.org/login', data=login_data, headers=headers, allow_redirects=True)
    response.raise_for_status()

    # Check if login was successful
    if 'email' in response.text and 'password' in response.text and 'type="submit"' in response.text:
        raise ValueError("Login failed - check credentials")

    console.print("[green]Logged in successfully[/green]")
    return session

def scrape_all_submissions(session, base_url="https://nsa-codebreaker.org/my-submissions"):
    """Scrape all submission pages with progress bar"""
    all_submissions = []

    # Start with the base page
    response = session.get(base_url)
    response.raise_for_status()
    data = response.json()

    if not data:
        console.print("[red]Failed to get initial submissions data[/red]")
        return []

    all_submissions.extend(data.get('submissions', []))
    total_count = data.get('total_count', 0)
    per_page = data.get('per_page', 10)
    total_pages = math.ceil(total_count / per_page)

    console.print(f"[cyan]Total submissions: {total_count}[/cyan]")
    console.print(f"[cyan]Total pages: {total_pages}[/cyan]")

    # Create progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console
    ) as progress:
        task = progress.add_task("[cyan]Scraping submissions...", total=total_pages)
        progress.update(task, advance=1)  # First page already done

        # Continue with numbered pages while there's a next page
        page = 2
        while data.get('next') and page <= total_pages:
            page_url = f"{base_url}/{page}"
            response = session.get(page_url)
            response.raise_for_status()
            data = response.json()

            if not data:
                console.print(f"[red]Failed to get page {page}, stopping[/red]")
                break

            all_submissions.extend(data.get('submissions', []))
            progress.update(task, advance=1)
            page += 1

    return all_submissions

def analyze_submissions(submissions):
    """Analyze submissions to get stats per task"""
    task_data = defaultdict(lambda: {
        'submissions': [],
        'count': 0,
        'first_at': None,
        'last_at': None,
        'time_spent_hours': 0
    })

    # Group submissions by task
    for sub in submissions:
        task = sub['task']
        at = sub['at']

        task_data[task]['submissions'].append(sub)
        task_data[task]['count'] += 1

        # Parse timestamp
        timestamp = datetime.fromisoformat(at.replace('Z', '+00:00'))

        if task_data[task]['first_at'] is None or timestamp < task_data[task]['first_at']:
            task_data[task]['first_at'] = timestamp

        if task_data[task]['last_at'] is None or timestamp > task_data[task]['last_at']:
            task_data[task]['last_at'] = timestamp

    # Calculate time spent
    # Sort tasks by number to process in order
    sorted_task_names = sorted(task_data.keys(), key=lambda x: int(x.replace('task', '')))
    now = datetime.now(datetime.fromisoformat(submissions[0]['at'].replace('Z', '+00:00')).tzinfo)
    latest_task = sorted_task_names[-1] if sorted_task_names else None

    # Check if task7 was fully completed (doesn't have failure message)
    task7_completed = False
    if latest_task == 'task7' and 'task7' in task_data:
        fail_text = "It didn't work."
        for sub in task_data['task7']['submissions']:
            if 'message' in sub and fail_text not in sub.get('message', ''):
                task7_completed = True
                break

    for i, task in enumerate(sorted_task_names):
        data = task_data[task]
        is_latest_task = (task == latest_task)

        if data['first_at'] and data['last_at']:
            # For the latest task (not completed), calculate to now (tracks ongoing work)
            if is_latest_task and not (task == 'task7' and task7_completed):
                time_diff = now - data['first_at']
                data['time_spent_hours'] = round(time_diff.total_seconds() / 3600, 2)
            # For completed tasks (including task7 if fully completed)
            else:
                # Calculate from previous task completion to this task completion
                if i > 0:
                    prev_task = sorted_task_names[i - 1]
                    prev_last = task_data[prev_task]['last_at']
                    if prev_last:
                        time_diff = data['last_at'] - prev_last
                        data['time_spent_hours'] = round(time_diff.total_seconds() / 3600, 2)
                    else:
                        data['time_spent_hours'] = 0
                else:
                    # First task: use time between first and last submission
                    time_diff = data['last_at'] - data['first_at']
                    data['time_spent_hours'] = round(time_diff.total_seconds() / 3600, 2)

    return dict(task_data)

def display_results(task_data):
    """Display results using rich"""
    # Sort tasks by task number
    sorted_tasks = sorted(task_data.keys(), key=lambda x: int(x.replace('task', '')))

    # Create table
    table = Table(title="NSA Codebreaker Submission Statistics", show_header=True, header_style="bold magenta")
    table.add_column("Task", style="cyan", width=10)
    table.add_column("Attempts", justify="right", style="yellow")
    table.add_column("Time Spent", justify="right", style="green")

    total_attempts = 0
    total_hours = 0

    for task in sorted_tasks:
        data = task_data[task]
        total_attempts += data['count']
        total_hours += data['time_spent_hours']

        time_spent = f"{data['time_spent_hours']:.2f}h" if data['time_spent_hours'] > 0 else "0h"
        task_number = task.replace('task', '')

        table.add_row(
            task_number,
            str(data['count']),
            time_spent
        )

    # Add summary row
    table.add_section()
    table.add_row(
        "[bold]TOTAL[/bold]",
        f"[bold]{total_attempts}[/bold]",
        f"[bold]{total_hours:.2f}h[/bold]"
    )

    console.print("\n")
    console.print(table)
    console.print("\n")

    # Additional stats
    console.print(Panel(
        f"[bold cyan]Summary:[/bold cyan]\n"
        f"Total Tasks Attempted: {len(sorted_tasks)}\n"
        f"Total Submissions: {total_attempts}\n"
        f"Total Time Since Start: {total_hours:.2f} hours ({total_hours/24:.1f} days)",
        title="Overall Statistics",
        border_style="green"
    ))

def save_results(submissions, task_data, filename="submission_stats.json"):
    """Save results to JSON file"""
    # Convert datetime objects to strings for JSON serialization
    serializable_task_data = {}
    for task, data in task_data.items():
        serializable_task_data[task] = {
            'count': data['count'],
            'time_spent_hours': data['time_spent_hours'],
            'first_at': data['first_at'].isoformat() if data['first_at'] else None,
            'last_at': data['last_at'].isoformat() if data['last_at'] else None
        }

    results = {
        'total_submissions': len(submissions),
        'task_statistics': serializable_task_data,
        'all_submissions': submissions
    }

    filepath = DATA_DIR / filename
    with open(filepath, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Results saved to {filepath}")

def main():
    parser = argparse.ArgumentParser(description='Scrape NSA Codebreaker submissions')
    parser.add_argument('--display', action='store_true', help='Display results from existing JSON without scraping')
    args = parser.parse_args()

    # If display flag is set, just load and display existing results
    if args.display:
        filepath = DATA_DIR / 'submission_stats.json'
        console.print(f"[cyan]Loading results from {filepath}...[/cyan]")
        try:
            with open(filepath, 'r') as f:
                results = json.load(f)

            submissions = results.get('all_submissions', [])
            if not submissions:
                console.print("[red]No submissions found in JSON file![/red]")
                return

            console.print(f"[green]Loaded {len(submissions)} submissions from file[/green]")

            # Analyze submissions
            task_data = analyze_submissions(submissions)

            # Display results
            display_results(task_data)

        except FileNotFoundError:
            console.print(f"[red]Error: {filepath} not found. Run without --display to scrape first.[/red]")
        except json.JSONDecodeError:
            console.print(f"[red]Error: Invalid JSON in {filepath}[/red]")
        return

    console.print("[bold cyan]Starting NSA Codebreaker submissions scraper...[/bold cyan]\n")

    # Log in and get session
    try:
        session = login()
    except ValueError as e:
        console.print(f"[red]Login failed: Incorrect credentials[/red]")
        return

    # Scrape all submissions
    console.print()
    submissions = scrape_all_submissions(session)

    if not submissions:
        console.print("[red]No submissions found![/red]")
        return

    console.print(f"\n[green]Found {len(submissions)} total submissions[/green]\n")

    # Analyze submissions
    task_data = analyze_submissions(submissions)

    # Display results
    display_results(task_data)

    # Save results
    save_results(submissions, task_data)

if __name__ == "__main__":
    main()
