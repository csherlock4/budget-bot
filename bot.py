import discord
from discord.ext import commands
import json
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
BUDGET_CHANNEL_ID = int(os.getenv('BUDGET_CHANNEL_ID', 0))

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Data file path
DATA_FILE = 'data.json'


def load_data():
    """Load budget data from JSON file"""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {'buckets': {}, 'transactions': []}


def save_data(data):
    """Save budget data to JSON file"""
    with open(DATA_FILE, 'w') as f:
        json.dump(data, f, indent=2)


@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print(f'Budget tracking active in channel ID: {BUDGET_CHANNEL_ID}')


@bot.command(name='setbucket', help='Set a budget bucket. Usage: !setbucket <emote> <name> <amount>')
async def set_bucket(ctx, emote: str, name: str, amount: float):
    """Set or update a budget bucket with an emote, name, and target amount"""
    data = load_data()

    # Store bucket info with emote as key
    data['buckets'][emote] = {
        'name': name,
        'target': amount,
        'emote': emote
    }

    save_data(data)
    await ctx.send(f'✅ Bucket set: {emote} **{name}** - Target: ${amount:.2f}')


@bot.command(name='buckets', help='List all budget buckets and their status')
async def list_buckets(ctx):
    """List all buckets with current balance and goal progress"""
    data = load_data()

    if not data['buckets']:
        await ctx.send('No buckets set up yet. Use `!setbucket <emote> <name> <amount>` to create one.')
        return

    embed = discord.Embed(title="💰 Budget Buckets", color=discord.Color.green())

    for emote, bucket in data['buckets'].items():
        name = bucket['name']
        limit_or_goal = bucket['target']

        # Calculate current balance (deposits - withdrawals)
        balance = sum(
            t['amount'] for t in data['transactions']
            if t['bucket'] == emote
        )

        # Check if this is a credit card bucket
        is_credit_card = name.lower() == 'creditcard'

        if is_credit_card:
            # For credit cards: show debt (negative balance) and available credit
            debt = abs(balance)  # Debt is the negative of balance
            available_credit = limit_or_goal - debt
            utilization = (debt / limit_or_goal * 100) if limit_or_goal > 0 else 0

            # Color code based on credit utilization
            if utilization > 90:
                status_emoji = '❌'
                color_indicator = 'red'
            elif utilization > 50:
                status_emoji = '🟡'
                color_indicator = 'yellow'
            else:
                status_emoji = '✅'
                color_indicator = 'green'

            embed.add_field(
                name=f"{emote} {name}",
                value=f"Debt: ${debt:.2f}\nLimit: ${limit_or_goal:.2f}\nAvailable: ${available_credit:.2f} ({utilization:.1f}% used)\n{status_emoji}",
                inline=True
            )
        else:
            # Regular savings bucket
            percentage = (balance / limit_or_goal * 100) if limit_or_goal > 0 else 0
            remaining_to_goal = limit_or_goal - balance

            # Color code based on progress
            if balance >= limit_or_goal:
                status_emoji = '✅'
                status_text = f"Goal reached! ${balance - limit_or_goal:.2f} over"
            elif percentage >= 75:
                status_emoji = '🟡'
                status_text = f"${remaining_to_goal:.2f} to goal"
            else:
                status_emoji = '🔵'
                status_text = f"${remaining_to_goal:.2f} to goal"

            embed.add_field(
                name=f"{emote} {name}",
                value=f"Balance: ${balance:.2f}\nGoal: ${limit_or_goal:.2f} ({percentage:.1f}%)\n{status_emoji} {status_text}",
                inline=True
            )

    await ctx.send(embed=embed)


@bot.command(name='income', help='Record income. Usage: !income <amount> <description>')
async def add_income(ctx, amount: float, *, description: str = "Income"):
    """Record income earned by a person"""
    data = load_data()

    # Record income transaction
    income_transaction = {
        'date': datetime.now().isoformat(),
        'amount': amount,
        'description': description,
        'person': ctx.author.name,
        'type': 'income'
    }

    if 'income' not in data:
        data['income'] = []

    data['income'].append(income_transaction)
    save_data(data)

    # Calculate total income for this person
    person_total = sum(
        i['amount'] for i in data['income']
        if i['person'] == ctx.author.name
    )

    # Calculate overall total income
    overall_total = sum(i['amount'] for i in data['income'])

    embed = discord.Embed(
        title=f"💵 Income Recorded",
        description=f"**${amount:.2f}** - {description}",
        color=discord.Color.green()
    )
    embed.add_field(name=f"{ctx.author.name}'s Total Income", value=f"${person_total:.2f}", inline=True)
    embed.add_field(name="Combined Income", value=f"${overall_total:.2f}", inline=True)

    await ctx.send(embed=embed)


@bot.command(name='incomehistory', help='View income history. Usage: !incomehistory [person_name]')
async def income_history(ctx, *, person: str = None):
    """View income history, optionally filtered by person"""
    data = load_data()

    if 'income' not in data or not data['income']:
        await ctx.send('No income recorded yet. Use `!income <amount> <description>` to add income.')
        return

    income_records = data['income']

    if person:
        income_records = [i for i in income_records if i['person'].lower() == person.lower()]
        title = f"💵 Income History: {person}"
    else:
        title = "💵 All Income History"

    if not income_records:
        await ctx.send(f'No income found for {person}.')
        return

    # Show last 10 income records
    income_records = sorted(income_records, key=lambda x: x['date'], reverse=True)[:10]

    embed = discord.Embed(title=title, color=discord.Color.green())

    # Add summary
    total = sum(i['amount'] for i in (data['income'] if not person else [i for i in data['income'] if i['person'].lower() == person.lower()]))
    embed.description = f"Total: **${total:.2f}**"

    for i in income_records:
        date = datetime.fromisoformat(i['date']).strftime('%m/%d/%Y %I:%M %p')
        embed.add_field(
            name=f"${i['amount']:.2f} - {i['person']}",
            value=f"{i['description']}\n{date}",
            inline=False
        )

    await ctx.send(embed=embed)


@bot.command(name='history', help='View transaction history. Usage: !history [emote]')
async def history(ctx, emote: str = None):
    """View transaction history, optionally filtered by bucket"""
    data = load_data()

    transactions = data['transactions']

    if emote:
        transactions = [t for t in transactions if t['bucket'] == emote]
        if emote in data['buckets']:
            title = f"Transaction History: {emote} {data['buckets'][emote]['name']}"
        else:
            title = f"Transaction History: {emote}"
    else:
        title = "All Transaction History"

    if not transactions:
        await ctx.send('No transactions found.')
        return

    # Show last 10 transactions
    transactions = sorted(transactions, key=lambda x: x['date'], reverse=True)[:10]

    embed = discord.Embed(title=title, color=discord.Color.blue())

    for t in transactions:
        date = datetime.fromisoformat(t['date']).strftime('%m/%d/%Y %I:%M %p')
        bucket_name = data['buckets'].get(t['bucket'], {}).get('name', 'Unknown')
        embed.add_field(
            name=f"{t['bucket']} {bucket_name} - ${abs(t['amount']):.2f}",
            value=f"{t['description']}\n{date}",
            inline=False
        )

    await ctx.send(embed=embed)


@bot.command(name='commands', help='List all available bot commands')
async def list_commands(ctx):
    """Display all available commands with descriptions"""
    embed = discord.Embed(
        title="📋 Budget Bot Commands",
        description="Here are all available commands:",
        color=discord.Color.purple()
    )

    embed.add_field(
        name="🏦 Setup & Management",
        value=(
            "`!setbucket <emote> <name> <amount>` - Create/update a budget bucket\n"
            "Example: `!setbucket 💰 home 5000`\n\n"
            "`!buckets` - View all buckets with balances and goals\n\n"
            "`!clear` - Clear all data (use with caution!)"
        ),
        inline=False
    )

    embed.add_field(
        name="💵 Income Tracking",
        value=(
            "`!income <amount> <description>` - Record income earned\n"
            "Example: `!income 3000 November paycheck`\n\n"
            "`!incomehistory [person]` - View income history (optional: filter by person)\n"
            "Example: `!incomehistory` or `!incomehistory Cassandra`"
        ),
        inline=False
    )

    embed.add_field(
        name="💰 Transaction Tracking",
        value=(
            "**In budget channel, use format:** `<emote> <amount> <description> [CC]`\n"
            "• Positive amount = deposit to bucket\n"
            "• Negative amount = withdrawal from bucket\n"
            "• Add 'CC' at end for credit card purchases\n\n"
            "Examples:\n"
            "`💰 2000 paycheck deposit`\n"
            "`💰 -100 groceries CC`\n"
            "`💳 500 credit card payment`"
        ),
        inline=False
    )

    embed.add_field(
        name="📊 Reports & History",
        value=(
            "`!summary` - Overall financial summary (income, savings, debt)\n\n"
            "`!history [emote]` - View transaction history (optional: filter by bucket)\n"
            "Example: `!history` or `!history 💰`"
        ),
        inline=False
    )

    embed.add_field(
        name="💳 Credit Card Tips",
        value=(
            "• Name a bucket 'CreditCard' to track as debt\n"
            "• Add 'CC' to transactions to dual-track (deduct from bucket + add to CC debt)\n"
            "• CC buckets show debt/limit instead of balance/goal"
        ),
        inline=False
    )

    await ctx.send(embed=embed)


@bot.command(name='summary', help='View overall financial summary including income')
async def summary(ctx):
    """Show summary of income and spending by person"""
    data = load_data()

    embed = discord.Embed(title="📊 Financial Summary", color=discord.Color.blue())

    # Income summary
    if 'income' in data and data['income']:
        total_income = sum(i['amount'] for i in data['income'])

        # Group by person
        people = {}
        for i in data['income']:
            person = i['person']
            if person not in people:
                people[person] = 0
            people[person] += i['amount']

        income_text = f"**Combined Total:** ${total_income:.2f}\n"
        for person, amount in people.items():
            income_text += f"• {person}: ${amount:.2f}\n"

        embed.add_field(name="💵 Income", value=income_text, inline=False)
    else:
        embed.add_field(name="💵 Income", value="No income recorded yet", inline=False)

    # Bucket summary
    if data['buckets']:
        total_saved = 0
        total_goals = 0
        cc_debt = 0

        for emote, bucket in data['buckets'].items():
            balance = sum(
                t['amount'] for t in data['transactions']
                if t['bucket'] == emote
            )

            if bucket['name'].lower() == 'creditcard':
                cc_debt += abs(balance)
            else:
                total_saved += balance
                total_goals += bucket['target']

        buckets_text = f"**Total Saved:** ${total_saved:.2f}\n"
        buckets_text += f"**Total Goals:** ${total_goals:.2f}\n"
        if cc_debt > 0:
            buckets_text += f"**CC Debt:** ${cc_debt:.2f}"

        embed.add_field(name="💰 Buckets", value=buckets_text, inline=False)
    else:
        embed.add_field(name="💰 Buckets", value="No buckets set up yet", inline=False)

    # Net worth (if income exists)
    if 'income' in data and data['income']:
        total_income = sum(i['amount'] for i in data['income'])
        total_saved = sum(
            sum(t['amount'] for t in data['transactions'] if t['bucket'] == emote)
            for emote, bucket in data['buckets'].items()
            if bucket['name'].lower() != 'creditcard'
        )
        cc_debt = sum(
            abs(sum(t['amount'] for t in data['transactions'] if t['bucket'] == emote))
            for emote, bucket in data['buckets'].items()
            if bucket['name'].lower() == 'creditcard'
        )

        net_position = total_saved - cc_debt
        unallocated = total_income - total_saved - cc_debt

        embed.add_field(
            name="📈 Overall",
            value=f"**Net Position:** ${net_position:.2f}\n**Unallocated Funds:** ${unallocated:.2f}",
            inline=False
        )

    await ctx.send(embed=embed)


@bot.command(name='clear', help='Clear all data (use with caution!)')
async def clear_data(ctx):
    """Clear all budget data"""
    save_data({'buckets': {}, 'transactions': []})
    await ctx.send('🗑️ All data cleared.')


@bot.event
async def on_message(message):
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return

    # Process commands first
    await bot.process_commands(message)

    # Check if message is in budget channel and starts with an emote
    if BUDGET_CHANNEL_ID == 0 or message.channel.id != BUDGET_CHANNEL_ID:
        return

    # Skip if it's a command
    if message.content.startswith('!'):
        return

    # Try to parse transaction format: <emote> <amount> <description>
    parts = message.content.split(maxsplit=2)

    if len(parts) < 2:
        return

    emote = parts[0]

    # Check if second part is a number (amount)
    try:
        amount = float(parts[1])
    except ValueError:
        return

    description = parts[2] if len(parts) > 2 else "No description"

    # Check if transaction ends with "CC" (credit card purchase)
    is_cc_purchase = description.upper().endswith(' CC')
    if is_cc_purchase:
        description = description[:-3].strip()  # Remove " CC" from description

    # Load data and check if bucket exists
    data = load_data()

    if emote not in data['buckets']:
        await message.reply(f"❌ Unknown bucket: {emote}. Use `!setbucket` to create it first.")
        return

    bucket = data['buckets'][emote]

    # Record transaction for the primary bucket
    transaction = {
        'date': datetime.now().isoformat(),
        'bucket': emote,
        'amount': amount,
        'description': description,
        'message_id': message.id,
        'cc_purchase': is_cc_purchase
    }

    data['transactions'].append(transaction)

    # If it's a CC purchase and it's a withdrawal, also charge the credit card
    cc_emote = None
    if is_cc_purchase and amount < 0:
        # Find the CreditCard bucket
        for bucket_emote, bucket_data in data['buckets'].items():
            if bucket_data['name'].lower() == 'creditcard':
                cc_emote = bucket_emote
                break

        if cc_emote:
            # Record charge on credit card (negative = debt increases)
            cc_transaction = {
                'date': datetime.now().isoformat(),
                'bucket': cc_emote,
                'amount': amount,  # Keep negative to represent debt
                'description': f"{description} (from {bucket['name']})",
                'message_id': message.id,
                'cc_purchase': False
            }
            data['transactions'].append(cc_transaction)

    save_data(data)

    # Calculate current balance (deposits - withdrawals)
    balance = sum(
        t['amount'] for t in data['transactions']
        if t['bucket'] == emote
    )

    limit_or_goal = bucket['target']
    is_credit_card = bucket['name'].lower() == 'creditcard'

    # Create response based on bucket type
    if is_credit_card:
        # Credit card bucket response
        debt = abs(balance)
        available_credit = limit_or_goal - debt
        utilization = (debt / limit_or_goal * 100) if limit_or_goal > 0 else 0

        transaction_type = "Payment" if amount > 0 else "Charge"

        if utilization > 90:
            status = f"❌ **${debt:.2f}** debt (${available_credit:.2f} available)"
            color = discord.Color.red()
        elif utilization > 50:
            status = f"🟡 **${debt:.2f}** debt (${available_credit:.2f} available)"
            color = discord.Color.gold()
        else:
            status = f"✅ **${debt:.2f}** debt (${available_credit:.2f} available)"
            color = discord.Color.green()

        embed = discord.Embed(
            title=f"{emote} {bucket['name']}",
            description=status,
            color=color
        )
        embed.add_field(name=f"This {transaction_type}", value=f"${abs(amount):.2f} - {description}", inline=False)
        embed.add_field(name="Utilization", value=f"${debt:.2f} / ${limit_or_goal:.2f} ({utilization:.1f}%)", inline=True)
    else:
        # Regular savings bucket response
        percentage = (balance / limit_or_goal * 100) if limit_or_goal > 0 else 0
        remaining_to_goal = limit_or_goal - balance

        transaction_type = "Deposit" if amount > 0 else "Withdrawal"
        cc_note = " (via CC)" if is_cc_purchase else ""

        if balance >= limit_or_goal:
            status = f"✅ Goal reached! **${balance:.2f}** (${balance - limit_or_goal:.2f} over goal)"
            color = discord.Color.green()
        elif percentage >= 75:
            status = f"🟡 **${balance:.2f}** (${remaining_to_goal:.2f} to goal)"
            color = discord.Color.gold()
        else:
            status = f"🔵 **${balance:.2f}** (${remaining_to_goal:.2f} to goal)"
            color = discord.Color.blue()

        embed = discord.Embed(
            title=f"{emote} {bucket['name']}",
            description=status,
            color=color
        )
        embed.add_field(name=f"This {transaction_type}{cc_note}", value=f"${abs(amount):.2f} - {description}", inline=False)
        embed.add_field(name="Progress", value=f"${balance:.2f} / ${limit_or_goal:.2f} ({percentage:.1f}%)", inline=True)

        # If CC purchase was made, add note about credit card
        if cc_emote and is_cc_purchase:
            cc_debt = abs(sum(
                t['amount'] for t in data['transactions']
                if t['bucket'] == cc_emote
            ))
            embed.add_field(name="💳 CC Update", value=f"Charged to credit card. New debt: ${cc_debt:.2f}", inline=False)

    await message.reply(embed=embed)


if __name__ == '__main__':
    if not TOKEN:
        print("Error: DISCORD_TOKEN not found in .env file")
        print("Please copy .env.example to .env and add your bot token")
        exit(1)

    bot.run(TOKEN)
