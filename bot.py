import discord
from discord.ext import commands
from discord import ui
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

# Store pending transactions (amount waiting for category selection)
pending_transactions = {}


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


def get_total_income(data):
    """Calculate total income"""
    if 'income' not in data:
        return 0.0
    return sum(i['amount'] for i in data['income'])


def get_total_allocated(data):
    """Calculate total allocated across all buckets"""
    return sum(bucket.get('allocated', 0.0) for bucket in data['buckets'].values())


def get_unallocated(data):
    """Calculate unallocated funds (income - allocated)"""
    return get_total_income(data) - get_total_allocated(data)


def get_spent(data, emote):
    """Calculate total spent from a bucket"""
    return sum(
        abs(t['amount']) for t in data['transactions']
        if t['bucket'] == emote and t['amount'] < 0
    )


def get_available(data, emote):
    """Calculate available balance in a bucket (allocated - spent)"""
    bucket = data['buckets'].get(emote, {})
    allocated = bucket.get('allocated', 0.0)
    spent = get_spent(data, emote)
    return allocated - spent


def find_bucket_by_name(data, name):
    """Find a bucket by partial name match (case insensitive)"""
    name_lower = name.lower()

    # First try exact match
    for emote, bucket in data['buckets'].items():
        if bucket['name'].lower() == name_lower:
            return emote, bucket

    # Then try partial match
    for emote, bucket in data['buckets'].items():
        if name_lower in bucket['name'].lower():
            return emote, bucket

    return None, None


class CategorySelectView(ui.View):
    """Interactive view for selecting a transaction category"""

    def __init__(self, user_id, amount, original_message):
        super().__init__(timeout=300)  # 5 minute timeout
        self.user_id = user_id
        self.amount = amount
        self.original_message = original_message

        # Load buckets and create buttons
        data = load_data()

        # Create buttons for each bucket (max 25 buttons per view)
        # For spending, show available balance and style accordingly
        for emote, bucket in list(data['buckets'].items())[:25]:
            available = get_available(data, emote)

            # Determine button style based on available balance (only for spending)
            if self.amount < 0:  # Spending
                if available < 0:
                    style = discord.ButtonStyle.secondary  # Gray - overspent
                    label = f"{bucket['name']} (-${abs(available):.0f})"
                elif available == 0:
                    style = discord.ButtonStyle.secondary  # Gray - empty
                    label = f"{bucket['name']} ($0)"
                elif available < abs(self.amount):
                    style = discord.ButtonStyle.danger  # Red - insufficient funds for this purchase
                    label = f"{bucket['name']} (${available:.0f})"
                else:
                    style = discord.ButtonStyle.success  # Green - sufficient funds
                    label = f"{bucket['name']} (${available:.0f})"
            else:  # Allocation
                style = discord.ButtonStyle.primary
                label = f"{bucket['name']}"

            button = ui.Button(
                label=label,
                emoji=emote,
                style=style
            )
            button.callback = self.create_callback(emote, bucket['name'])
            self.add_item(button)

    def create_callback(self, emote, bucket_name):
        """Create a callback function for each button"""
        async def callback(interaction: discord.Interaction):
            # Verify it's the right user
            if interaction.user.id != self.user_id:
                await interaction.response.send_message("This isn't your transaction!", ephemeral=True)
                return

            data = load_data()
            bucket = data['buckets'][emote]

            # Handle allocation vs spending
            if self.amount > 0:
                # This is an allocation - add to bucket's allocated amount
                bucket['allocated'] = bucket.get('allocated', 0.0) + self.amount
                data['buckets'][emote] = bucket
                save_data(data)

                allocated = bucket['allocated']
                target = bucket['target']
                percentage = (allocated / target * 100) if target > 0 else 0

                embed = discord.Embed(
                    title=f"{emote} {bucket['name']}",
                    description=f"✅ Allocated ${self.amount:.2f}",
                    color=discord.Color.green()
                )
                embed.add_field(name="Total Allocated", value=f"${allocated:.2f}", inline=True)
                embed.add_field(name="Target", value=f"${target:.2f} ({percentage:.0f}%)", inline=True)

                unallocated = get_unallocated(data)
                embed.add_field(name="💰 Unallocated Remaining", value=f"${unallocated:.2f}", inline=False)

                await interaction.response.edit_message(
                    content=f"✅ Allocated ${self.amount:.2f} to {emote} {bucket_name}",
                    view=None,
                    embed=embed
                )
            else:
                # This is spending - record transaction
                available_before = get_available(data, emote)

                transaction = {
                    'date': datetime.now().isoformat(),
                    'bucket': emote,
                    'amount': self.amount,
                    'description': 'Quick transaction',
                    'message_id': self.original_message.id,
                    'cc_purchase': False
                }

                data['transactions'].append(transaction)
                save_data(data)

                # Calculate envelope balances
                allocated = bucket.get('allocated', 0.0)
                spent = get_spent(data, emote)
                available = allocated - spent

                # Determine status and color
                if available < 0:
                    status = f"⚠️ OVERSPENT by ${abs(available):.2f}!"
                    color = discord.Color.red()
                elif available == 0:
                    status = f"💸 Envelope empty"
                    color = discord.Color.orange()
                elif available < allocated * 0.25:
                    status = f"🟡 Running low"
                    color = discord.Color.gold()
                else:
                    status = f"✅ On track"
                    color = discord.Color.green()

                embed = discord.Embed(
                    title=f"{emote} {bucket['name']}",
                    description=status,
                    color=color
                )
                embed.add_field(name="This Expense", value=f"${abs(self.amount):.2f}", inline=False)
                embed.add_field(name="Allocated", value=f"${allocated:.2f}", inline=True)
                embed.add_field(name="Spent", value=f"${spent:.2f}", inline=True)
                embed.add_field(name="Available", value=f"${available:.2f}", inline=True)

                # Add warning if overspent
                if available_before >= 0 and available < 0:
                    embed.add_field(
                        name="⚠️ Warning",
                        value=f"This purchase put you ${abs(available):.2f} over budget!",
                        inline=False
                    )

                await interaction.response.edit_message(
                    content=f"✅ Spent ${abs(self.amount):.2f} from {emote} {bucket_name}",
                    view=None,
                    embed=embed
                )

            # Clean up pending transaction
            if self.user_id in pending_transactions:
                del pending_transactions[self.user_id]

        return callback


@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!', flush=True)
    print(f'Budget tracking active in channel ID: {BUDGET_CHANNEL_ID}', flush=True)
    print(f'Bot ready at {datetime.now()}', flush=True)


@bot.command(name='setbucket', help='Set a budget bucket. Usage: !setbucket <emote> <name> <amount>')
async def set_bucket(ctx, emote: str, name: str, amount: float):
    """Set or update a budget bucket with an emote, name, and target amount"""
    data = load_data()

    # Preserve allocated amount if bucket already exists
    existing_allocated = 0.0
    if emote in data['buckets']:
        existing_allocated = data['buckets'][emote].get('allocated', 0.0)

    # Store bucket info with emote as key
    data['buckets'][emote] = {
        'name': name,
        'target': amount,
        'emote': emote,
        'allocated': existing_allocated
    }

    save_data(data)
    await ctx.send(f'✅ Bucket set: {emote} **{name}** - Target: ${amount:.2f}')


@bot.command(name='buckets', help='List all budget buckets (envelopes) and their status')
async def list_buckets(ctx):
    """List all buckets with allocated, spent, and available amounts"""
    data = load_data()

    print(f"DEBUG: buckets command called, found {len(data.get('buckets', {}))} buckets")

    if not data.get('buckets'):
        print("DEBUG: No buckets found, sending error message")
        await ctx.send('No buckets set up yet. Use `!setbucket <emote> <name> <amount>` to create one.')
        return

    print("DEBUG: Buckets found, building embed")

    embed = discord.Embed(title="💰 Budget Envelopes", color=discord.Color.green())

    # Add unallocated summary
    total_income = get_total_income(data)
    total_allocated = get_total_allocated(data)
    unallocated = get_unallocated(data)

    if total_income > 0:
        embed.description = f"💵 Income: ${total_income:.2f} | 💰 Unallocated: ${unallocated:.2f}"

    for emote, bucket in data['buckets'].items():
        name = bucket['name']
        target = bucket['target']
        allocated = bucket.get('allocated', 0.0)
        spent = get_spent(data, emote)
        available = allocated - spent

        # Determine status emoji
        if allocated == 0:
            status_emoji = '⚪'  # Not funded
            status_text = "Not allocated"
        elif available < 0:
            status_emoji = '❌'  # Overspent
            status_text = f"OVERSPENT ${abs(available):.2f}"
        elif available == 0:
            status_emoji = '💸'  # Empty
            status_text = "Empty"
        elif available < allocated * 0.25:
            status_emoji = '🟡'  # Running low
            status_text = f"${available:.2f} left"
        else:
            status_emoji = '✅'  # Good
            status_text = f"${available:.2f} left"

        # Build field value
        value_parts = []
        if allocated > 0:
            value_parts.append(f"Allocated: ${allocated:.2f}")
            value_parts.append(f"Spent: ${spent:.2f}")
            value_parts.append(f"Available: ${available:.2f}")
        else:
            value_parts.append(f"Target: ${target:.2f}")
            value_parts.append("(not yet allocated)")

        value_parts.append(f"{status_emoji} {status_text}")

        embed.add_field(
            name=f"{emote} {name}",
            value="\n".join(value_parts),
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

    # Calculate unallocated funds
    unallocated = get_unallocated(data)
    allocated = get_total_allocated(data)

    embed = discord.Embed(
        title=f"💵 Income Recorded",
        description=f"**${amount:.2f}** - {description}",
        color=discord.Color.green()
    )
    embed.add_field(name=f"{ctx.author.name}'s Total Income", value=f"${person_total:.2f}", inline=True)
    embed.add_field(name="Combined Income", value=f"${overall_total:.2f}", inline=True)
    embed.add_field(name="💰 Unallocated", value=f"${unallocated:.2f}", inline=False)

    if unallocated > 0:
        embed.add_field(
            name="💡 Next Step",
            value=f"Allocate funds to envelopes! Type `+<amount> <category>` (e.g., `+600 groceries`)",
            inline=False
        )

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
        title="📋 Envelope Budget Bot",
        description="Simple envelope budgeting system. Track income, allocate to envelopes, and spend!",
        color=discord.Color.purple()
    )

    embed.add_field(
        name="🏦 Setup",
        value=(
            "`!setbucket <emote> <name> <target>` - Create/update an envelope\n"
            "Example: `!setbucket 🥕 groceries 600`\n\n"
            "`!buckets` - View all envelopes and their status\n\n"
            "`!clear` - Clear all data (use with caution!)"
        ),
        inline=False
    )

    embed.add_field(
        name="💵 Step 1: Record Income",
        value=(
            "`!income <amount> <description>` - Record income\n"
            "Example: `!income 3000 paycheck`\n\n"
            "Shows your unallocated funds after recording."
        ),
        inline=False
    )

    embed.add_field(
        name="💰 Step 2: Allocate to Envelopes",
        value=(
            "**Quick allocation:** `+<amount> <category>`\n"
            "Examples:\n"
            "`+600 groceries` - Allocate $600 to groceries envelope\n"
            "`+150 gas` - Allocate $150 to gas\n"
            "`+920 mortgage` - Allocate $920 to mortgage\n\n"
            "Fuzzy matching works! `+600 groc` finds groceries."
        ),
        inline=False
    )

    embed.add_field(
        name="💸 Step 3: Spend from Envelopes",
        value=(
            "**Quick spending:** Just type `-<amount>`\n"
            "Examples:\n"
            "`-28` - Bot shows category buttons with available balances\n"
            "`-150` - Click the envelope to spend from\n\n"
            "Buttons are color-coded:\n"
            "• Green = enough funds\n"
            "• Red = insufficient funds (warns if overspent)\n"
            "• Gray = empty envelope"
        ),
        inline=False
    )

    embed.add_field(
        name="📊 Reports",
        value=(
            "`!summary` - Envelope budget overview\n"
            "`!history [emote]` - Transaction history\n"
            "`!incomehistory [person]` - Income history"
        ),
        inline=False
    )

    await ctx.send(embed=embed)


@bot.command(name='summary', help='View overall financial summary (envelope budget)')
async def summary(ctx):
    """Show summary of income, allocations, and spending"""
    data = load_data()

    embed = discord.Embed(title="📊 Envelope Budget Summary", color=discord.Color.blue())

    # Income summary
    total_income = get_total_income(data)

    if total_income > 0:
        # Group by person
        people = {}
        for i in data.get('income', []):
            person = i['person']
            if person not in people:
                people[person] = 0
            people[person] += i['amount']

        income_text = f"**Total:** ${total_income:.2f}\n"
        for person, amount in people.items():
            income_text += f"• {person}: ${amount:.2f}\n"

        embed.add_field(name="💵 Income", value=income_text, inline=False)
    else:
        embed.add_field(name="💵 Income", value="No income recorded yet. Use `!income <amount> <description>`", inline=False)

    # Envelope summary
    if data['buckets']:
        total_allocated = get_total_allocated(data)
        total_spent = sum(get_spent(data, emote) for emote in data['buckets'].keys())
        total_available = total_allocated - total_spent
        unallocated = get_unallocated(data)

        envelope_text = f"**Allocated:** ${total_allocated:.2f}\n"
        envelope_text += f"**Spent:** ${total_spent:.2f}\n"
        envelope_text += f"**Available:** ${total_available:.2f}\n"
        envelope_text += f"**Unallocated:** ${unallocated:.2f}"

        # Add warning if over-allocated
        if unallocated < 0:
            envelope_text += f"\n⚠️ Over-allocated by ${abs(unallocated):.2f}!"

        embed.add_field(name="💰 Envelopes", value=envelope_text, inline=False)

        # Show overspent envelopes
        overspent = []
        for emote, bucket in data['buckets'].items():
            available = get_available(data, emote)
            if available < 0:
                overspent.append(f"{emote} {bucket['name']}: ${abs(available):.2f} over")

        if overspent:
            embed.add_field(
                name="⚠️ Overspent Envelopes",
                value="\n".join(overspent),
                inline=False
            )
    else:
        embed.add_field(name="💰 Envelopes", value="No envelopes set up yet", inline=False)

    await ctx.send(embed=embed)


@bot.command(name='undo', help='Undo the last transaction or allocation')
async def undo_last(ctx):
    """Undo the most recent transaction or allocation"""
    data = load_data()

    # Check if there are any transactions
    if data['transactions']:
        # Remove the last transaction
        last_transaction = data['transactions'].pop()
        save_data(data)

        bucket = data['buckets'].get(last_transaction['bucket'], {})
        await ctx.send(f"✅ Undone: ${abs(last_transaction['amount']):.2f} from {last_transaction['bucket']} {bucket.get('name', 'Unknown')}")
        return

    # Check if there are any recent allocations (look at buckets with allocated > 0)
    # Since we don't track allocation history, we can't undo allocations automatically
    # User would need to manually adjust with negative allocation

    await ctx.send("❌ No transactions to undo. To undo an allocation, you'll need to manually adjust it.")


@bot.command(name='adjust', help='Adjust allocation for a bucket. Usage: !adjust <emote> <amount>')
async def adjust_allocation(ctx, emote: str, amount: float):
    """Manually adjust the allocated amount for a bucket (can be negative to reduce)"""
    data = load_data()

    if emote not in data['buckets']:
        await ctx.send(f"❌ Unknown bucket: {emote}. Use `!buckets` to see all categories.")
        return

    bucket = data['buckets'][emote]
    old_allocated = bucket.get('allocated', 0.0)
    new_allocated = old_allocated + amount

    if new_allocated < 0:
        await ctx.send(f"❌ Can't adjust: would result in negative allocation (${new_allocated:.2f})")
        return

    bucket['allocated'] = new_allocated
    data['buckets'][emote] = bucket
    save_data(data)

    unallocated = get_unallocated(data)

    embed = discord.Embed(
        title=f"{emote} {bucket['name']}",
        description=f"✅ Adjusted allocation",
        color=discord.Color.blue()
    )
    embed.add_field(name="Previous", value=f"${old_allocated:.2f}", inline=True)
    embed.add_field(name="Adjustment", value=f"{'+' if amount > 0 else ''}${amount:.2f}", inline=True)
    embed.add_field(name="New Total", value=f"${new_allocated:.2f}", inline=True)
    embed.add_field(name="💰 Unallocated", value=f"${unallocated:.2f}", inline=False)

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

    # Check for quick transaction format (just a number like "-28" or "+99" or "150")
    content = message.content.strip()
    try:
        amount = float(content)
        # It's a quick transaction! Show category selection
        data = load_data()

        if not data['buckets']:
            await message.reply("❌ No buckets set up yet. Use `!setbucket` to create categories first.")
            return

        # Store pending transaction
        pending_transactions[message.author.id] = {
            'amount': amount,
            'message': message
        }

        # Create and send category selection view
        view = CategorySelectView(message.author.id, amount, message)

        transaction_type = "deposit" if amount > 0 else "expense"
        embed = discord.Embed(
            title=f"💰 ${abs(amount):.2f} {transaction_type}",
            description="Select a category for this transaction:",
            color=discord.Color.blue()
        )

        await message.reply(embed=embed, view=view)
        return
    except ValueError:
        # Not a simple number, continue to regular transaction parsing
        pass

    # Check for allocation format (+amount category)
    if content.startswith('+'):
        parts = content.split(maxsplit=1)
        if len(parts) >= 2:
            try:
                amount = float(parts[0])  # Will include the +
                category_name = parts[1]

                data = load_data()

                # Find the bucket by name
                emote, bucket = find_bucket_by_name(data, category_name)

                if not bucket:
                    await message.reply(f"❌ Couldn't find a bucket matching '{category_name}'. Use `!buckets` to see all categories.")
                    return

                # Check if there are unallocated funds
                unallocated = get_unallocated(data)

                # Allocate the funds
                bucket['allocated'] = bucket.get('allocated', 0.0) + amount
                data['buckets'][emote] = bucket
                save_data(data)

                allocated = bucket['allocated']
                target = bucket['target']
                percentage = (allocated / target * 100) if target > 0 else 0
                new_unallocated = get_unallocated(data)

                embed = discord.Embed(
                    title=f"{emote} {bucket['name']}",
                    description=f"✅ Allocated ${amount:.2f}",
                    color=discord.Color.green()
                )
                embed.add_field(name="Total Allocated", value=f"${allocated:.2f}", inline=True)
                embed.add_field(name="Target", value=f"${target:.2f} ({percentage:.0f}%)", inline=True)
                embed.add_field(name="💰 Unallocated Remaining", value=f"${new_unallocated:.2f}", inline=False)

                if new_unallocated < 0:
                    embed.add_field(
                        name="⚠️ Warning",
                        value=f"You've over-allocated by ${abs(new_unallocated):.2f}! You don't have enough income to cover all allocations.",
                        inline=False
                    )

                await message.reply(embed=embed)
                return
            except ValueError:
                # Not a valid allocation format, continue
                pass

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
