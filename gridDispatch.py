import gurobipy as gp
from gurobipy import GRB

def gridDispatch(bids, loads, transLimit):
    maxGen = [bid.amount for bid in bids]
    cost = [bid.price for bid in bids]
    loc = [bid.loc for bid in bids]
    env = gp.Env(empty=True)
    env.setParam("OutputFlag",0)
    env.start()
    m = gp.Model('dispatch', env=env)
    genNum = len(bids)
    gen = m.addVars(genNum, lb=0, ub=maxGen, name='gen')
    #genCons1 = m.addConstrs((gen[i] >= 0 for i in range(genNum)), name='genCons1')
    #genCons2 = m.addConstrs((gen[i] <= maxGen[i] for i in range(genNum)), name='genCons2')
    trans_01 = m.addVar(lb=-transLimit, ub=transLimit, name='trans_01')
    balance_loc0 = m.addConstr(gp.quicksum([gen[i] for i in range(genNum) if loc[i] == 0]) - trans_01 == loads[0], name='balance_loc0')
    balance_loc1 = m.addConstr(gp.quicksum([gen[i] for i in range(genNum) if loc[i] == 1]) + trans_01 == loads[1], name='balance_loc1')

    m.setObjective(gp.quicksum([gen[i] * cost[i] for i in range(genNum)]), GRB.MINIMIZE)
    m.optimize()

    if m.SolCount > 1:
        m.setParam(GRB.Param.SolutionNumber, 0)
    genSol = [(bids[i].id, gen[i].x) for i in range(genNum)]
    lmp = [balance_loc0.Pi, balance_loc1.Pi]
    return genSol, lmp
