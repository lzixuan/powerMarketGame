from pywebio import start_server
from pywebio.input import *
from pywebio.output import *
from pywebio.session import run_async
from functools import partial
import time
import asyncio
import json
import plotly.express as px
from gridDispatch import gridDispatch
import pandas as pd
import numpy as np

gameID_role = {
    1: {
        'round 1': 1,
        'round 2': 2
    },
    2: {
        'round 1': 2,
        'round 2': 4
    },
    3: {
        'round 1': 3,
        'round 2': 1
    },
    4: {
        'round 1': 4,
        'round 2': 3
    },
    5: {
        'round 1': 5,
        'round 2': 6
    },

}
roleID_gameID = {}

roleDescription = [
    'Plants that are running continuously over time and used to cater the base demand of the grid are said to be base-load power plants. Examples include nuclear, coal-fired, and combined cycles.\nYour power plant has large generation capacity and low marginal cost. But because of some physical and mechanical constraints (e.g. start or change output slowly), you will be penalized when not being dispatched.\nObjective: Maximize profit = market revenue - generation cost - penalty of not being dispatched\nOther Attributes:',
    'Renewable power plants are pivotal components of the modern and future power grid, providing clean and sustainable sources of electricity. They harness energy from naturally occurring and replenishable resources like sunlight, wind, water, and geothermal heat.\nYou own a wind/solar power plant, whose generation depends on the weather but comes at nearly zero cost. In addition, you can get government tax credit for the generation you sell ($3/MWh in 2022). In the power market, you want to sell as much as possible of your generation so that you can earn back your investment sooner.\nObjective: maximize market revenue=market revenue + tax credit',
    'As the gamemaster, you are equivalent to load-serving entities (e.g. ComEd) and grid operator. The "Clear Market" button will trigger a dispatch solver that selects the least-cost combination of generator bids to meet the load in two places and advance the game to next period.'
]

roleByRealPlayer = [False for i in range(0, 6)]

round = 1
period = 1

# renewable generation and load profiles
windProfile = [0.7, 0.4, 0.3, 0.6]
solarProfile = [0, 0.9, 0.8, 0]
locIdx_name = {0: 'South', 1: 'North'}
loadProfile = {
    0: [400, 600, 800, 550],
    1: [50, 60, 70, 40]
}
transLimit = {1: 5000, 2: 200}

periodBid_submitted = [False for i in range(0, 6)]
class bid:
    def __init__(self, amount, price, location, roleID):
        self.amount = amount
        self.price = price
        self.loc = location
        self.id = roleID
    def __lt__(self, other):
        return self.price < other.price

bids_period = {
    1: [],
    2: [],
    3: [],
    4: []
}
renewBidLimit = {}

clearingPrice = []
dispatchRes = {}
revenue = {}
profit = {}
# renewable tax credit
renewCredit = 3

def showMarketInfo(roles):
    with use_scope('market', clear=True):
        put_text('Generator Information:')
        tableHeader = ['Role ID', 'Fuel Type', 'Location', 'Player ID', 'Nameplate Capacity (MW)']
        tableContent = []
        windTotal = 0
        solarTotal = 0
        for i in range(1, 7):
            if i in roleID_gameID.keys():
                gameID = str(roleID_gameID[i])
            else:
                gameID = 'None'
            roleID = i
            role = roles[str(roleID)]
            if role['Fuel'] in ['wind', 'solar']:
                capacity = role['Nameplate Capacity (Maximum possible generation MW)']
                if role['Fuel'] == 'wind':
                    windTotal += capacity
                else:
                    solarTotal += capacity
            else:
                capacity = role['Capacity (MW)']
            row = [str(roleID), role['Fuel'], locIdx_name[role['Location']], gameID, str(capacity)]
            tableContent.append(row)
        put_table(tableContent, header=tableHeader)
        put_text('Renewable Generation Forecast:')
        renewDf = pd.DataFrame()
        period = [1, 2, 3, 4]
        renewDf['Period'] = period
        renewDf['Wind'] = [windTotal * w for w in windProfile]
        renewDf['Solar'] = [solarTotal * s for s in solarProfile]
        fig1 = px.bar(renewDf, x='Period', y=['Wind', 'Solar'])
        fig1.update_yaxes(range=[0, 1000])
        fig1.update_layout(yaxis_title='Generation (MW)')
        html = fig1.to_html(include_plotlyjs="require", full_html=False)
        put_html(html)
        put_text('Load Forecast:')
        loadDf = pd.DataFrame()
        period = [1, 2, 3, 4]
        loadDf['Period'] = period
        loadDf['South'] = loadProfile[0]
        loadDf['North'] = loadProfile[1]
        fig2 = px.bar(loadDf, x='Period', y=['South', 'North'])
        fig2.update_yaxes(range=[0, 1000])
        fig2.update_layout(yaxis_title='Load (MW)')
        html = fig2.to_html(include_plotlyjs="require", full_html=False)
        put_html(html)


def showBids(period):
    put_text(f'Round {round}, Period {period}')
    if len(bids_period[period]) > 0:
        prices = [bid.price for bid in bids_period[period]]
        amounts = [bid.amount for bid in bids_period[period]]
        fig = px.histogram(x=prices, y=amounts, histfunc='sum', nbins=50)
        lmp_loc0 = clearingPrice[period - 1][0]
        lmp_loc1 = clearingPrice[period - 1][1]
        fig.add_vline(x=lmp_loc0, line_dash='dash', line_color='firebrick', annotation_text='LMP_South', annotation_position='top left')
        fig.add_vline(x=lmp_loc1, line_dash='dash', line_color='firebrick', annotation_text='LMP_North', annotation_position='top right')
        html = fig.to_html(include_plotlyjs="require", full_html=False)
        put_html(html)

def showDispatch(period, roles):
    put_text(f'Locational Marginal Price (Market Clearing Price, $/MWh):\n South: {clearingPrice[period - 1][0]}, North: {clearingPrice[period - 1][1]}')
    tableHeader = ['Role', 'Fuel', 'Location', 'Player', 'Bid Capacity (MW)', 'Bid Price ($/MW)', 'Dispatch Result (MW)', 'Accum. Revenue ($)', 'Accum. Profit ($)']
    tableContent = []
    for i in range(1, 7):
        if i in roleID_gameID.keys():
            gameID = str(roleID_gameID[i])
        else:
            gameID = 'None'
        roleID = i
        role = roles[str(roleID)]
        row = [str(roleID), role['Fuel'], locIdx_name[role['Location']], gameID, str(sum([bid.amount for bid in bids_period[period] if bid.id == roleID])), str(sum([bid.price for bid in bids_period[period] if bid.id == roleID])), str(dispatchRes[i][period - 1]), str(revenue[i]), str(profit[i])]
        tableContent.append(row)
    put_table(tableContent, header=tableHeader)

def showMarketRes(roles):
    with use_scope('market', clear=True):
        for p in range(1, period):
            showBids(p)
            showDispatch(p, roles)

def showBidForm(role, roleID):
    global periodBid_submitted
    clear('market')
    with use_scope('bid', clear=True):
        if periodBid_submitted[roleID - 1]:
            put_text("You have submitted the bid for current period, please wait for the market clearing results.")
        else:
            '''
            def check_bid(data, capacity):
                if data['gen1'] < 0 or data['gen2'] < 0:
                    return 'Generation bids cannot be negative!'
                if data['gen1'] + data['gen2'] > capacity:
                    return 'Sum of generation bids cannot be higher than limit.'
            '''
            if role['Fuel'] in ['wind', 'solar']:
                capacity = renewBidLimit[str(roleID)]
            else:
                capacity = role['Capacity (MW)']
            # bid made in each period by each generator
            bidPrice = input(f'Period {period} Bid Price ($/MW) for {capacity} MW capacity', type=NUMBER, placeholder='0')
            bids_period[period].append(bid(capacity, bidPrice, role['Location'], roleID))
            periodBid_submitted[roleID - 1] = True
            '''
            bid = input_group("Make Generation Bids (Segment1+Segmeng2=capacity)",[
                input('Generation Segment1 (MW)', name='gen1', type=NUMBER),
                input('Bid Price for Segment1 ($/MW)', name='price1', type=NUMBER),
                input('Generation Segment2 (MW)', name='gen2', type=NUMBER),
                input('Bid Price for Segment2 ($/MW)', name='price2', type=NUMBER)
            ], validate=partial(check_bid,capacity=capacity))
            '''
# clear thge market using by solving the dispatch problem
def clearMarket(roles):
    global bids_period, dispatchRes
    for i in range(1, 7):
        # for roles not taken by real players, submit bids based on cost
        if not periodBid_submitted[i - 1]:
            role = roles[str(i)]
            if role['Fuel'] in ['wind', 'solar']:
                bidGen = renewBidLimit[str(i)]
                bidPrice = 0
                if role['Fuel'] == 'solar':
                    print(bidGen)
            else:
                bidGen = role['Capacity (MW)']
                bidPrice = role['Generation Cost ($/MWh)']
            bids_period[period].append(bid(bidGen, bidPrice, role['Location'], i))
    genSol, lmp = gridDispatch(bids_period[period], [loadProfile[0][period - 1], loadProfile[1][period - 1]], transLimit[round])
    for gen in genSol:
        dispatchRes[gen[0]].append(gen[1])
    clearingPrice.append(lmp)
    # calculate accumulated revenue and profit for each generator
    for i in range(1, 7):
        role = roles[str(i)]
        lmp = clearingPrice[period - 1][role['Location']]
        if role['Fuel'] in ['wind', 'solar']:
            revenue[i] += (lmp + renewCredit) * dispatchRes[i][period - 1]
            profit[i] += (lmp + renewCredit - role['Generation Cost ($/MWh)']) * dispatchRes[i][period - 1]
        else:
            if role['Fuel'] == 'coal':
                if dispatchRes[i][period - 1] == 0:
                    profit[i] -= role['Not-dispatched Penalty (per period)']
            revenue[i] += lmp * dispatchRes[i][period - 1]
            profit[i] += (lmp - role['Generation Cost ($/MWh)']) * dispatchRes[i][period - 1]

            

def control(choice, roles):
    if choice == 'View Market Information':
        showMarketInfo(roles)
    elif choice == 'View Market Results':
        showMarketRes(roles)

def control_GM(choice, roles):
    global round, period, renewBidLimit, dispatchRes, clearingPrice, periodBid_submitted, bids_period, revenue, profit
    if choice == 'View Market Information':
        showMarketInfo(roles)
    elif choice == 'Clear Market':
        if period <= 4:
            clearMarket(roles)
            # set bid limit for renewable generators in the next period
            # the bid limit can be regarded as actual generation that differs from forecast
            if period <= 3:
                for i in range(1, 7):
                    role = roles[str(i)]
                    if role['Fuel'] == 'wind':
                        renewBidLimit[str(i)] = int(role['Nameplate Capacity (Maximum possible generation MW)'] * windProfile[period] * np.random.normal(1, 0.1))
                    elif role['Fuel'] == 'solar':
                        renewBidLimit[str(i)] = int(role['Nameplate Capacity (Maximum possible generation MW)'] * solarProfile[period] * np.random.normal(1, 0.1))
                    periodBid_submitted[i - 1] = False
            period += 1
            showMarketRes(roles)
        else:
            toast('You have reached the final period. Please view market results and Wait until next round.')

    elif choice == 'Move to Next Round':
        if round == 1:
            clear('market')
            round = 2
            # reset the states
            period = 1
            roleID_gameID = {}
            periodBid_submitted = [False for i in range(0, 6)]
            bids_period = {
                1: [],
                2: [],
                3: [],
                4: []
            }
            clearingPrice = []
            # initialize the information for period 1
            for i in range(1, 7):
                role = roles[str(i)]
                if role['Fuel'] == 'wind':
                    renewBidLimit[str(i)] = int(role['Nameplate Capacity (Maximum possible generation MW)'] * windProfile[period - 1] * np.random.normal(1, 0.1))
                elif role['Fuel'] == 'solar':
                    renewBidLimit[str(i)] = int(role['Nameplate Capacity (Maximum possible generation MW)'] * solarProfile[period - 1] * np.random.normal(1, 0.1))
                dispatchRes[i] = []
                revenue[i] = 0
                profit[i] = 0

def checkID(id):
    if (not id in range(1, 7)) and (not id == 1000):
        return "Invalid ID!"

def makeRoleCard(role):
    description = roleDescription[role['DescriptionCode']]
    with use_scope('roleInfo', clear=True):
        put_text(description)
        for attrib in role.keys():
            if attrib != 'DescriptionCode':
                if attrib == 'Location':
                    put_text(f'{attrib}: {locIdx_name[role[attrib]]}')
                else:
                    put_text(f'{attrib}: {role[attrib]}')

def main():
    global roleID_gameID, dispatchRes
    roles = json.load(open('./generators.json'))
    id = input('Please input your game ID', type=NUMBER, required=True, validate=checkID)

    # game master interface
    if id == 1000:
        if round == 1:
            # initialize the information for period 1
            # NOTE: game master enters the game first
            for i in range(1, 7):
                role = roles[str(i)]
                if role['Fuel'] == 'wind':
                    renewBidLimit[str(i)] = int(role['Nameplate Capacity (Maximum possible generation MW)'] * windProfile[period - 1] * np.random.normal(1, 0.1))
                elif role['Fuel'] == 'solar':
                    renewBidLimit[str(i)] = int(role['Nameplate Capacity (Maximum possible generation MW)'] * solarProfile[period - 1] * np.random.normal(1, 0.1))
                dispatchRes[i] = []
                revenue[i] = 0
                profit[i] = 0
        put_text(roleDescription[2])
        put_buttons(['View Market Information', 'Clear Market', 'Move to Next Round'], onclick=partial(control_GM, roles=roles))
    # player interface
    else:
        while round <= 2:
            round_copy = round
            # set real player flag that indicates whether a role is played by real player
            roleID = gameID_role[id][f'round {round}']
            # map the role ID to game ID
            roleID_gameID[roleID] = id
            roleByRealPlayer[roleID - 1] = True
            role = roles[str(roleID)]
            makeRoleCard(role)
            with use_scope('control', clear=True):
                put_buttons(['View Market Information', 'View Market Results'], onclick=partial(control, roles=roles))
                put_button('Make Bid', onclick=partial(showBidForm, role=role, roleID=roleID))
            while period <= 4 and round_copy == round:
                period_copy = period
                with use_scope('info', clear=True):
                    put_text(f'Round: {round}, Market Period: {period}')
                    put_text(f'Accumulated Revenue: {revenue[roleID]}, Accumulated Profit: {profit[roleID]}')
                    if role['Fuel'] in ['wind', 'solar']:
                        capacity = renewBidLimit[str(roleID)]
                        put_text(f'Generation Limit in this period: {capacity} MW')
                
                while period_copy == period and round_copy == round:
                    time.sleep(0.2)
            while round_copy == round:
                time.sleep(0.2)
            


if __name__ == '__main__':
    start_server(main, debug=True, port=8001, host="localhost")