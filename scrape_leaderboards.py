#!/usr/bin/env python3

import requests
import json
import re
import argparse
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

console = Console()

# Create data directory
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

# Task configurations for each year
YEAR_TASK_CONFIGS = {
    2018: [
        (0, 0, "Main Leaderboard"),
        (1, 0, "Participants"),
    ],
    2019: [
        (0, 0, "Main Leaderboard"),
        (1, 0, "Participants"),
    ],
    2020: [
        (0, 0, "Main Leaderboard"),
        (1, 0, "Participants"),
    ],
    2021: [
        (0, 0, "Main Leaderboard"),
        (1, 0, "Participants"),
    ],
    2022: [
        (0, 0, "Main Leaderboard"),
        (1, 0, "Participants"),
    ],
    2023: [
        (0, 0, "Main Leaderboard"),
        (1, 0, "Participants"),
    ],
    2024: [
        (0, 0, "Main Leaderboard"),
        (1, 0, "Participants"),
    ],
    2025: [  # Current year
        (0, 0, "Main Leaderboard"),
        (1, 0, "Participants"),
    ],
}

def get_tokens():
    """Get session cookie and CSRF token from leaderboard page"""
    url = "https://nsa-codebreaker.org/leaderboard"

    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
    }

    console.print("[dim]Fetching session and CSRF token...[/dim]")

    try:
        session = requests.Session()
        response = session.get(url, headers=headers)
        response.raise_for_status()

        # Get session cookie
        session_token = session.cookies.get('session')

        # Extract CSRF token from HTML
        csrf_match = re.search(r'xhr\.setRequestHeader\(["\']X-CSRFToken["\']\s*,\s*["\']([^"\']+)["\']\)', response.text)

        if csrf_match and session_token:
            csrf_token = csrf_match.group(1)
            console.print(f"[green]Session token: {session_token[:20]}...[/green]")
            console.print(f"[green]CSRF token: {csrf_token[:20]}...[/green]")
            return session_token, csrf_token
        else:
            console.print("[red]Could not find session or CSRF token[/red]")
            return None, None

    except Exception as e:
        console.print(f"[red]Error fetching tokens: {e}[/red]")
        return None, None

def fetch_table_data(board_x, board_y, session_token, csrf_token, year=None):
    """Fetch data from the API endpoint"""
    if year:
        url = f"https://nsa-codebreaker.org/data/histboard/{year}/{board_x}/{board_y}"
    else:
        url = f"https://nsa-codebreaker.org/data/board/{board_x}/{board_y}"

    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
        'Cookie': f'session={session_token}',
        'X-CSRFToken': csrf_token,
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Referer': 'https://nsa-codebreaker.org/leaderboard'
    }

    payload = {
        'draw': 1,
        'start': 0,
        'length': -1  # -1 means get all records
    }

    try:
        response = requests.post(url, headers=headers, data=payload)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        console.print(f"[red]Error fetching {url}: {e}[/red]")
        return None

def scrape_leaderboard(year=None, session_token=None, csrf_token=None, progress=None, task_id=None):
    """Scrape the NSA Codebreaker leaderboard for a specific year"""
    # Get tokens if not provided
    if session_token is None or csrf_token is None:
        session_token, csrf_token = get_tokens()
        if not session_token or not csrf_token:
            raise ValueError("Failed to get session and CSRF tokens")

    year_label = year if year else 2025

    # Dictionary to store all scraped data
    scraped_data = {}

    # Get task configuration for this year
    tables_to_scrape = YEAR_TASK_CONFIGS.get(year_label, YEAR_TASK_CONFIGS[2025])

    # Fetch all tables in parallel using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submit all fetch tasks
        future_to_table = {
            executor.submit(fetch_table_data, board_x, board_y, session_token, csrf_token, year): table_name
            for board_x, board_y, table_name in tables_to_scrape
        }

        # Collect results as they complete
        for future in as_completed(future_to_table):
            table_name = future_to_table[future]
            try:
                api_response = future.result()
                if api_response and 'data' in api_response:
                    scraped_data[table_name] = api_response['data']
                else:
                    scraped_data[table_name] = []
            except Exception as e:
                console.print(f"[red]Error fetching {table_name}: {e}[/red]")
                scraped_data[table_name] = []

            if progress and task_id is not None:
                progress.update(task_id, advance=1, description=f"[cyan]Year {year_label}: {table_name}")

    return scraped_data, session_token, csrf_token

def analyze_participants(participants_data):
    """Analyze participants data to get total counts"""
    if not participants_data:
        return {"total_participants": 0, "by_school": []}

    total_participants = 0
    school_data = []

    for row in participants_data:
        if len(row) >= 2:
            school_name = row[0]
            try:
                if isinstance(row[1], str):
                    participant_count = int(row[1].replace(',', ''))
                else:
                    participant_count = int(row[1])
                total_participants += participant_count
                school_data.append({
                    'school': school_name,
                    'participants': participant_count
                })
            except (ValueError, TypeError):
                continue

    return {
        "total_participants": total_participants,
        "by_school": school_data
    }

def analyze_task_solves(main_leaderboard_data, year=2025):
    """Analyze task solve data from main leaderboard table"""
    task_stats = {}

    # Different years have different structures
    if year == 2025:
        # 2025 structure: [Division, Rank, School, Score, then 6 columns per task × 8 tasks]
        # Each task has 6 columns: [passed#, reached#, pass%, points, pts4reach, pts4pass]
        task_names = ["Task 0", "Task 1", "Task 2", "Task 3", "Task 4", "Task 5", "Task 6", "Task 7"]

        # Initialize task stats
        for task_name in task_names:
            task_stats[task_name] = {"total_solvers": 0, "schools": []}

        # Process each school's data
        for row in main_leaderboard_data:
            if len(row) >= 52:  # Need at least 52 columns (4 + 8*6)
                school_name = row[2]  # School is column 2

                # Process each task
                for task_idx, task_name in enumerate(task_names):
                    # Each task has 6 columns, "passed#" is the first column of each task group
                    col_idx = 4 + (task_idx * 6)
                    try:
                        if isinstance(row[col_idx], str):
                            solve_count = int(row[col_idx].replace(',', ''))
                        else:
                            solve_count = int(row[col_idx])
                        if solve_count > 0:
                            task_stats[task_name]["total_solvers"] += solve_count
                            task_stats[task_name]["schools"].append({
                                'school': school_name,
                                'solvers': solve_count
                            })
                    except (ValueError, IndexError, TypeError):
                        continue
    else:
        # Historical years: varying structures
        # Years 2018-2020: [School, Tasks..., Score]
        # Years 2021-2024: [Rank, School, Tasks..., Score]

        # Define task names, column indices, and school column for each year
        if year == 2018:
            # [School, Task0-7, Score] - 10 columns
            school_col = 0
            task_configs = [
                (1, "Task 0"), (2, "Task 1"), (3, "Task 2"), (4, "Task 3"),
                (5, "Task 4"), (6, "Task 5"), (7, "Task 6"), (8, "Task 7")
            ]
        elif year == 2019:
            # [School, Task1-7/6a/6b, Score] - 10 columns
            school_col = 0
            task_configs = [
                (1, "Task 1"), (2, "Task 2"), (3, "Task 3"), (4, "Task 4"),
                (5, "Task 5"), (6, "Task 6a"), (7, "Task 6b"), (8, "Task 7")
            ]
        elif year == 2020:
            # [School, Task1-9, Score] - 11 columns
            school_col = 0
            task_configs = [
                (1, "Task 1"), (2, "Task 2"), (3, "Task 3"), (4, "Task 4"),
                (5, "Task 5"), (6, "Task 6"), (7, "Task 7"), (8, "Task 8"), (9, "Task 9")
            ]
        elif year == 2021:
            # [Rank, School, Task0-10, Score] - 14 columns
            school_col = 1
            task_configs = [
                (2, "Task 0"), (3, "Task 1"), (4, "Task 2"), (5, "Task 3"),
                (6, "Task 4"), (7, "Task 5"), (8, "Task 6"), (9, "Task 7"),
                (10, "Task 8"), (11, "Task 9"), (12, "Task 10")
            ]
        elif year == 2022:
            # [Rank, School, Task0/a1/a2/b1/b2/5-9, Score] - 13 columns
            school_col = 1
            task_configs = [
                (2, "Task 0"), (3, "Task a1"), (4, "Task a2"), (5, "Task b1"),
                (6, "Task b2"), (7, "Task 5"), (8, "Task 6"), (9, "Task 7"),
                (10, "Task 8"), (11, "Task 9")
            ]
        elif year == 2023:
            # [Rank, School, Task0-9, Score] - 13 columns
            school_col = 1
            task_configs = [
                (2, "Task 0"), (3, "Task 1"), (4, "Task 2"), (5, "Task 3"),
                (6, "Task 4"), (7, "Task 5"), (8, "Task 6"), (9, "Task 7"),
                (10, "Task 8"), (11, "Task 9")
            ]
        elif year == 2024:
            # [Rank, School, Total, Task0-7, Score] - 12 columns (actually 11 in data)
            school_col = 1
            task_configs = [
                (2, "Task 0"), (3, "Task 1"), (4, "Task 2"), (5, "Task 3"),
                (6, "Task 4"), (7, "Task 5"), (8, "Task 6"), (9, "Task 7")
            ]
        else:
            # Default fallback
            school_col = 1
            task_configs = []

        # Initialize task stats
        for col_idx, task_name in task_configs:
            task_stats[task_name] = {"total_solvers": 0, "schools": []}

        # Process each school's data
        for row in main_leaderboard_data:
            if len(row) < 3:
                continue

            school_name = row[school_col]

            for col_idx, task_name in task_configs:
                try:
                    if len(row) <= col_idx:
                        continue

                    if isinstance(row[col_idx], str):
                        solve_count = int(row[col_idx].replace(',', ''))
                    else:
                        solve_count = int(row[col_idx])

                    if solve_count > 0:
                        task_stats[task_name]["total_solvers"] += solve_count
                        task_stats[task_name]["schools"].append({
                            'school': school_name,
                            'solvers': solve_count
                        })
                except (ValueError, IndexError, TypeError):
                    continue

    return task_stats

def calculate_solve_rates(participants_total, task_stats):
    """Calculate solve rates for each task"""
    solve_rates = {}

    for task_name, stats in task_stats.items():
        total_solvers = stats["total_solvers"]
        solve_rate = (total_solvers / participants_total * 100) if participants_total > 0 else 0

        solve_rates[task_name] = {
            "total_solvers": total_solvers,
            "total_participants": participants_total,
            "solve_rate_percent": round(solve_rate, 2)
        }

    return solve_rates

def save_results(data, filename="leaderboard_stats.json"):
    """Save results to JSON file"""
    filepath = DATA_DIR / filename
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    console.print(f"[green]Results saved to {filepath}[/green]")

def load_archived_data():
    """Load archived leaderboard data"""
    filepath = DATA_DIR / 'archived_leaderboards.json'
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        console.print(f"[yellow]Warning: {filepath} is corrupted, starting fresh[/yellow]")
        return {}

def save_archived_data(archive):
    """Save archived leaderboard data"""
    filepath = DATA_DIR / 'archived_leaderboards.json'
    with open(filepath, 'w') as f:
        json.dump(archive, f, indent=2)
    console.print(f"[green]Archived data saved to {filepath}[/green]")

def display_summary(total_participants, total_schools, year=2025):
    """Display overall summary statistics"""
    summary_text = f"""
[bold cyan]NSA Codebreaker Challenge Statistics ({year})[/bold cyan]

[yellow]Total Participants:[/yellow] {total_participants:,}
[yellow]Total Schools:[/yellow] {total_schools:,}
    """
    console.print(Panel(summary_text, title="Challenge Overview", border_style="blue"))

def task_sort_key(task_name):
    """Create sort key for task names to handle variants like 6a, 6b, a1, b2, etc."""
    # Extract the part after "Task "
    task_part = task_name.replace("Task ", "")

    # Handle different formats:
    # "5" -> (5, '', 0)
    # "6a" -> (6, 'a', 0)
    # "a1" -> (0, 'a', 1) - special case for 2022, comes after Task 0
    # "b2" -> (0, 'b', 2) - special case for 2022

    import re

    # Try to match patterns
    if task_part.isdigit():
        # Simple number: "5"
        return (int(task_part), '', 0)
    elif re.match(r'^\d+[a-z]$', task_part):
        # Number followed by letter: "6a"
        num = int(task_part[:-1])
        letter = task_part[-1]
        return (num, letter, 0)
    elif re.match(r'^[a-z]\d+$', task_part):
        # Letter followed by number: "a1", "b2" (2022 format)
        letter = task_part[0]
        num = int(task_part[1:])
        # Put these between 0 and 5
        return (0, letter, num)
    else:
        # Fallback
        return (999, task_part, 0)

def display_solve_rates(solve_rates):
    """Display task solve rates in a formatted table"""
    # Get total participants from first task (same for all tasks)
    total_participants = next(iter(solve_rates.values()))['total_participants'] if solve_rates else 0

    table = Table(
        title=f"Task Solve Rates (Total Participants: {total_participants:,})",
        show_header=True,
        header_style="bold magenta"
    )

    table.add_column("Task", style="cyan", no_wrap=True)
    table.add_column("Solvers", justify="right")
    table.add_column("Solve Rate", justify="right")

    # Sort tasks by custom key that handles variants
    sorted_tasks = sorted(solve_rates.items(), key=lambda x: task_sort_key(x[0]))

    for task_name, stats in sorted_tasks:
        solve_rate = stats['solve_rate_percent']
        solvers = stats['total_solvers']

        # Color code based on solve rate
        if solve_rate >= 25:
            color = "green"
        elif solve_rate >= 2:
            color = "yellow"
        else:
            color = "red"

        # Strip "Task " prefix for display
        task_display = task_name.replace("Task ", "")

        table.add_row(
            task_display,
            f"[{color}]{solvers:,}[/{color}]",
            f"[{color}]{solve_rate:.2f}%[/{color}]"
        )

    console.print(table)

def load_and_display(filename="leaderboard_stats_2025.json", year=None):
    """Load data from JSON file or archive and display it"""
    # If a specific year is requested, try to load from archive
    if year is not None and year != 2025:
        archive = load_archived_data()
        year_key = str(year)

        if year_key in archive:
            results = archive[year_key]
        else:
            console.print(f"[red]Error: Year {year} not found in archive. Run with --year {year} to scrape it first.[/red]")
            sys.exit(1)
    else:
        # Load from specified file
        filepath = DATA_DIR / filename
        try:
            with open(filepath, 'r') as f:
                results = json.load(f)
        except FileNotFoundError:
            console.print(f"[red]Error: {filepath} not found. Run without --display to scrape data first.[/red]")
            sys.exit(1)
        except json.JSONDecodeError:
            console.print(f"[red]Error: Invalid JSON in {filepath}[/red]")
            sys.exit(1)

    # Extract data from results
    participants_analysis = results.get('participants_analysis', {})
    total_participants = participants_analysis.get('total_participants', 0)
    total_schools = len(participants_analysis.get('by_school', []))
    solve_rates = results.get('solve_rates', {})

    # Display results with rich
    display_year = results.get('year', 2025)
    console.print()
    display_summary(total_participants, total_schools, display_year)
    console.print()
    display_solve_rates(solve_rates)

def main():
    parser = argparse.ArgumentParser(description="NSA Codebreaker leaderboard scraper and stats viewer")
    parser.add_argument("--display", "-d", action="store_true", help="Display data from existing JSON file without scraping")
    parser.add_argument("--file", "-f", default="leaderboard_stats_2025.json", help="JSON file to display (default: leaderboard_stats_2025.json)")
    parser.add_argument("--year", "-y", type=int, help="Year to scrape (e.g., 2018-2024). If not specified, scrapes current year")
    parser.add_argument("--all-years", "-a", action="store_true", help="Scrape all available years (2018-2024 and current)")
    args = parser.parse_args()

    if args.display:
        # Just display existing data
        console.print("[bold cyan]Loading and displaying existing data...[/bold cyan]\n")
        load_and_display(args.file, args.year)
    else:
        # Scrape and display
        console.print("[bold cyan]Starting NSA Codebreaker leaderboard scraper...[/bold cyan]\n")

        # Determine which years to scrape
        if args.all_years:
            years_to_scrape = [2018, 2019, 2020, 2021, 2022, 2023, 2024, None]  # None = current year
        elif args.year:
            years_to_scrape = [args.year]
        else:
            years_to_scrape = [None]  # Current year only

        # Load archived data
        archive = load_archived_data()

        # Filter out years that already exist in archive (except current year)
        years_to_actually_scrape = []
        years_to_display = []

        for year in years_to_scrape:
            year_label = year if year else 2025
            year_key = str(year_label)

            # Always scrape current year, skip archived years
            if year is None or year_key not in archive:
                years_to_actually_scrape.append(year)
            else:
                console.print(f"[yellow]Year {year_label} already exists in archive, skipping scrape[/yellow]")

            years_to_display.append(year)

        # Get tokens once
        session_token = None
        csrf_token = None

        # Scrape years that need scraping
        if years_to_actually_scrape:
            # Calculate total tasks for progress bar
            total_tasks = sum(len(YEAR_TASK_CONFIGS.get(y if y else 2025, YEAR_TASK_CONFIGS[2025]))
                            for y in years_to_actually_scrape)

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console
            ) as progress:
                task = progress.add_task("[cyan]Scraping leaderboards...", total=total_tasks)

                for year in years_to_actually_scrape:
                    year_label = year if year else 2025

                    # Scrape the data
                    scraped_data, session_token, csrf_token = scrape_leaderboard(year, session_token, csrf_token, progress, task)

                    if not scraped_data:
                        console.print(f"[red]Failed to scrape data for {year_label}[/red]")
                        continue

                    # Analyze participants
                    participants_analysis = analyze_participants(scraped_data.get("Participants", []))
                    total_participants = participants_analysis['total_participants']
                    total_schools = len(participants_analysis['by_school'])

                    # Analyze task solves from main leaderboard data
                    main_leaderboard_data = scraped_data.get("Main Leaderboard", [])
                    task_stats = analyze_task_solves(main_leaderboard_data, year_label)

                    # Calculate solve rates
                    solve_rates = calculate_solve_rates(total_participants, task_stats)

                    # Compile final results
                    results = {
                        "year": year_label,
                        "participants_analysis": participants_analysis,
                        "task_statistics": task_stats,
                        "solve_rates": solve_rates,
                        "raw_data": scraped_data
                    }

                    # Save to archive or current year file
                    if year is None:  # Current year
                        save_results(results, args.file)
                    else:  # Historical year - add to archive
                        archive[str(year_label)] = results

        # Save archive if we added anything to it
        if any(y is not None for y in years_to_actually_scrape):
            save_archived_data(archive)

        # Display results for all requested years
        for year in years_to_display:
            year_label = year if year else 2025
            year_key = str(year_label)

            # Load results from appropriate location
            if year is None:
                filepath = DATA_DIR / args.file
                try:
                    with open(filepath, 'r') as f:
                        results = json.load(f)
                except FileNotFoundError:
                    console.print(f"[red]Could not load data for {year_label}[/red]")
                    continue
            else:
                if year_key in archive:
                    results = archive[year_key]
                else:
                    console.print(f"[red]Could not load data for {year_label}[/red]")
                    continue

            # Extract data
            participants_analysis = results.get('participants_analysis', {})
            total_participants = participants_analysis.get('total_participants', 0)
            total_schools = len(participants_analysis.get('by_school', []))
            solve_rates = results.get('solve_rates', {})

            # Display results with rich
            console.print()
            display_summary(total_participants, total_schools, year_label)
            console.print()
            display_solve_rates(solve_rates)

            if len(years_to_display) > 1 and year != years_to_display[-1]:
                console.print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    main()
