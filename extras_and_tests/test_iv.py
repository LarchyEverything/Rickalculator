import math
import csv

def getMortyStats(number):
    with open('All_Mortys.csv', 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if row['Number'] == str(number):
                return {
                    'Number': row['Number'],
                    'Name': row['Name'],
                    'Type': row['Type'],
                    'Rarity': row['Rarity'],
                    'XP': int(row['xp']),
                    'HP': int(row['hp']),
                    'ATK': int(row['atk']),
                    'DEF': int(row['def']),
                    'SPD': int(row['spd']),
                    'Total': int(row['total']),
                    'NumberToEvolve': row['NumberToEvolve'] or None,
                    'BadgesRequired': row['BadgesRequired'] if row['BadgesRequired'] != 'N/A' else None
                }
    return None


def calculate_hp(base_hp, iv, level, ev):
    ev_bonus = math.floor(math.sqrt(ev) / 4)
    return math.floor((base_hp + iv + ev_bonus + 50) * (level / 50)) + 10

def calculate_hp_iv(hp, base_hp, level, ev):
    possible_ivs = []
    for iv in range(17):  # 0 to 16 inclusive
        if calculate_hp(base_hp, iv, level, ev) == hp:
            possible_ivs.append(iv)
    if len(possible_ivs) == 1:
        return possible_ivs[0]
    elif len(possible_ivs) > 1:
        return (min(possible_ivs), max(possible_ivs))
    else:
        return None  # No valid IV found

def calculate_stat(base_stat, iv, level, ev):
    ev_bonus = math.floor(math.sqrt(ev) / 4)
    return math.floor((base_stat + iv + ev_bonus) * (level / 50)) + 5

def calculate_stat_iv(stat, base_stat, level, ev):
    possible_ivs = []
    for iv in range(17):  # 0 to 16 inclusive
        if calculate_stat(base_stat, iv, level, ev) == stat:
            possible_ivs.append(iv)
    
    if len(possible_ivs) == 1:
        return possible_ivs[0]
    elif len(possible_ivs) > 1:
        return (min(possible_ivs), max(possible_ivs))
    else:
        return None  # No valid IV found

def calculate_iv(mortyNumber, level, hp, attack, defence, spd, ev):
    morty = getMortyStats(mortyNumber)
    hp = calculate_hp_iv(hp, morty['HP'], level, ev)
    attack = calculate_stat_iv(attack, morty['ATK'], level, ev)
    defence = calculate_stat_iv(defence, morty['DEF'], level, ev)
    spd = calculate_stat_iv(spd, morty['SPD'], level, ev)
    return hp, attack, defence, spd

#calculate_iv(441,20,82,51,49,53,0)
calculate_iv(429,40,134,110,111,81,0)
calculate_iv(429,40,137,110,111,81,0)

