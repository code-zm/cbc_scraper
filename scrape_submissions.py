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
import hashlib
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

# Success message hashes for tasks 0-6 (SHA 256)
SUCCESS_HASHES = {
    'task0': '4210a265099e340d98e4b3d04e883245cde32999133c83f3af2931dcc5c440c3',
    'task1': '7e08cced5248f6d7f49d15ab6d410c1acf0aac1a04d5c1345e558b0ed0e86c42',
    'task2': '6f6ea131f6c4a001614adb60fe208e54b1da6dcd4aeef850cf4645dcc3ad0832',
    'task3': '537f4e3753b644d6d682dd43176841d957f970452a65897f72e486a17df3971d',
    'task4': 'c3a7e5b47da78cf8b07b6364f1a79fab02c1d5a6d35f36e04659a2157681af33',
    'task5': '6fa5737d513388d1e067927248ee33f0bef6f5909e3c56d72a0f1054e0a88f24',
    'task6': 'cac8981e08fe56e8b30807e24d5d08d0fab3beea9ef8538e42f036ced3e5052e',
}

def check_task_passed(task_name, submissions):
    """Check if a task was passed by looking at response message hashes.

    For tasks 0-6: Check if any submission has a response message hash matching the success hash
    For task 7: Check if the latest submission doesn't contain the failure message
    """
    if task_name == 'task7':
        # Task 7 uses the old method (check for failure message)
        fail_text = "It didn't work."
        latest_sub = max(submissions, key=lambda s: datetime.fromisoformat(s['at'].replace('Z', '+00:00')))
        return 'message' in latest_sub and fail_text not in latest_sub.get('message', '')

    # For tasks 0-6, check if any submission has the success message hash
    if task_name not in SUCCESS_HASHES:
        return False

    success_hash = SUCCESS_HASHES[task_name]
    for sub in submissions:
        if 'message' in sub and sub['message']:
            msg_hash = hashlib.sha256(sub['message'].encode()).hexdigest()
            if msg_hash == success_hash:
                return True

    return False

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

    # Check which tasks were passed using response message hashes
    task_passed = {}
    for task in sorted_task_names:
        task_passed[task] = check_task_passed(task, task_data[task]['submissions'])

    # If the latest task with submissions was passed, add the next task (even if no submissions yet)
    if latest_task and task_passed.get(latest_task, False):
        latest_task_num = int(latest_task.replace('task', ''))
        if latest_task_num < 7:  # Only if not already on task 7
            next_task = f'task{latest_task_num + 1}'
            if next_task not in task_data:
                # Add placeholder for the next task they're working on
                task_data[next_task] = {
                    'submissions': [],
                    'count': 0,
                    'first_at': task_data[latest_task]['last_at'],  # Start from when they passed previous task
                    'last_at': task_data[latest_task]['last_at'],
                    'time_spent_hours': 0
                }
                sorted_task_names.append(next_task)
                sorted_task_names.sort(key=lambda x: int(x.replace('task', '')))
                task_passed[next_task] = False
                latest_task = next_task

    for i, task in enumerate(sorted_task_names):
        data = task_data[task]
        is_latest_task = (task == latest_task)
        passed = task_passed[task]

        if data['first_at'] and data['last_at']:
            # For the latest task that hasn't been passed yet, calculate to now (tracks ongoing work)
            if is_latest_task and not passed:
                time_diff = now - data['first_at']
                data['time_spent_hours'] = round(time_diff.total_seconds() / 3600, 2)
            # For passed tasks
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
