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
    """List all buckets with current spending and remaining amounts"""
    data = load_data()

    if not data['buckets']:
        await ctx.send('No buckets set up yet. Use `!setbucket <emote> <name> <amount>` to create one.')
        return

    embed = discord.Embed(title="💰 Budget Buckets", color=discord.Color.green())

    for emote, bucket in data['buckets'].items():
        name = bucket['name']
        target = bucket['target']

        # Calculate total spent in this bucket
        spent = sum(
            abs(t['amount']) for t in data['transactions']
            if t['bucket'] == emote and t['amount'] < 0
        )

        remaining = target - spent
        percentage = (spent / target * 100) if target > 0 else 0

        # Color code based on budget status
        status_emoji = '✅' if remaining > 0 else '❌'

        embed.add_field(
            name=f"{emote} {name}",
            value=f"Target: ${target:.2f}\nSpent: ${spent:.2f}\nRemaining: ${remaining:.2f} ({percentage:.1f}%)\n{status_emoji}",
            inline=True
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

    # Load data and check if bucket exists
    data = load_data()

    if emote not in data['buckets']:
        await message.reply(f"❌ Unknown bucket: {emote}. Use `!setbucket` to create it first.")
        return

    bucket = data['buckets'][emote]

    # Record transaction
    transaction = {
        'date': datetime.now().isoformat(),
        'bucket': emote,
        'amount': amount,
        'description': description,
        'message_id': message.id
    }

    data['transactions'].append(transaction)
    save_data(data)

    # Calculate remaining budget
    spent = sum(
        abs(t['amount']) for t in data['transactions']
        if t['bucket'] == emote and t['amount'] < 0
    )

    remaining = bucket['target'] - spent
    percentage = (spent / bucket['target'] * 100) if bucket['target'] > 0 else 0

    # Create response
    if remaining > 0:
        status = f"✅ **${remaining:.2f}** remaining ({100-percentage:.1f}% left)"
        color = discord.Color.green() if percentage < 75 else discord.Color.orange()
    else:
        status = f"❌ **${abs(remaining):.2f}** over budget!"
        color = discord.Color.red()

    embed = discord.Embed(
        title=f"{emote} {bucket['name']}",
        description=status,
        color=color
    )
    embed.add_field(name="This Transaction", value=f"${abs(amount):.2f} - {description}", inline=False)
    embed.add_field(name="Total Spent", value=f"${spent:.2f} / ${bucket['target']:.2f}", inline=True)

    await message.reply(embed=embed)


if __name__ == '__main__':
    if not TOKEN:
        print("Error: DISCORD_TOKEN not found in .env file")
        print("Please copy .env.example to .env and add your bot token")
        exit(1)

    bot.run(TOKEN)
