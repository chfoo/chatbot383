import random
import sqlite3
import collections

import sys

COLORS = (
    'black',
    'blue',
    'brown',
    'gray',
    'green',
    'pink',
    'purple',
    'red',
    'white',
    'yellow',
)
TYPES = (
    'normal',
    'fighting',
    'flying',
    'poison',
    'ground',
    'rock',
    'bug',
    'ghost',
    'steel',
    'fire',
    'water',
    'grass',
    'electric',
    'psychic',
    'ice',
    'dragon',
    'dark',
    'fairy',
)
WEIGHTS = (
    'light',
    'medium',
    'heavy',
)
WEIGHT_SORTINGS = (
    'light-to-heavy',
    'heavy-to-light',
)
VERSUS = (
    'vs',
    '/',
    'versus',
    'vs.',
)


PokemonInfo = collections.namedtuple('PokemonInfo', ['id', 'name', 'weight'])


class MatchError(ValueError):
    pass


class MatchGenerator(object):
    def __init__(self, db_path):
        self._path = db_path
        self._con = sqlite3.connect(db_path)

    def get_match_string(self, args):
        blue_team, red_team = self.pick_teams(args)

        return '{} vs {} ({}/{})'.format(
            ', '.join(info.name for info in blue_team),
            ', '.join(info.name for info in red_team),
            ','.join(str(info.id) for info in blue_team),
            ','.join(str(info.id) for info in red_team),
        )

    def pick_teams(self, args):
        blue_team_color = None
        blue_team_weight = None
        blue_team_weight_sort = 'light-to-heavy'
        blue_team_type = None

        red_team_color = None
        red_team_weight = None
        red_team_weight_sort = 'light-to-heavy'
        red_team_type = None

        arg_list = list(args)

        while arg_list:
            arg = arg_list.pop(0)

            if arg in COLORS:
                blue_team_color = arg
            elif arg in WEIGHTS:
                blue_team_weight = arg
            elif arg in WEIGHT_SORTINGS:
                blue_team_weight_sort = arg
            elif arg in TYPES:
                blue_team_type = arg
            elif arg in VERSUS:
                break
            else:
                raise MatchError('Unrecognized option {}'.format(arg))

        if not blue_team_color and not blue_team_weight and not blue_team_type:
            if random.random() < 0.7:
                blue_team_color = random.choice(COLORS)
            else:
                blue_team_type = random.choice(TYPES)

        if not arg_list:
            red_team_color = blue_team_color
            red_team_weight = blue_team_weight
            red_team_weight_sort = blue_team_weight_sort
            red_team_type = blue_team_type

        while arg_list:
            arg = arg_list.pop(0)

            if arg in COLORS:
                red_team_color = arg
            elif arg in WEIGHTS:
                red_team_weight = arg
            elif arg in WEIGHT_SORTINGS:
                red_team_weight_sort = arg
            elif arg in TYPES:
                red_team_type = arg
            else:
                raise MatchError('Unrecognized option {}'.format(arg))

        blue_team = self.pick_three(blue_team_color, blue_team_weight,
                                    blue_team_weight_sort, blue_team_type)
        red_team = self.pick_three(red_team_color, red_team_weight,
                                   red_team_weight_sort, red_team_type,
                                   not_ids=[item.id for item in blue_team])

        return blue_team, red_team

    def pick_three(self, color=None, weight=None, weight_sort='light-to-heavy',
                   type_=None, not_ids=None):
        query = '''SELECT
            pokemon.id,
            pokemon_species_names.name,
            pokemon.weight
            FROM pokemon
            JOIN pokemon_species_names ON pokemon.id == pokemon_species_names.pokemon_species_id AND
                pokemon_species_names.local_language_id = 9
            JOIN pokemon_species ON pokemon.id == pokemon_species.id
            JOIN pokemon_colors ON
                pokemon_species.color_id == pokemon_colors.id
            JOIN pokemon_types ON pokemon.id = pokemon_types.pokemon_id
            JOIN types ON pokemon_types.type_id = types.id
            WHERE pokemon.id <= 493
            '''

        args = []

        if color:
            query += ''' AND pokemon_colors.identifier = ?'''
            args.append(color)

        if weight:
            # DB has weight in kg * 10
            if weight == 'light':
                query += ''' AND pokemon.weight < 1102'''
            elif weight == 'medium':
                query += ''' AND pokemon.weight >= 1102
                AND pokemon.weight < 3307'''
            else:
                query += ''' AND pokemon.weight >= 3307'''

        if type_:
            if type_ in ('normal', 'fairy'):
                query += ''' AND types.identifier in ('normal', 'fairy')'''
            else:
                query += ''' AND types.identifier = ?'''
                args.append(type_)

        if not_ids:
            assert len(not_ids) == 3
            query += ''' AND pokemon.id NOT IN (?, ?, ?)'''
            args.extend(not_ids)

        query += ''' GROUP BY pokemon.id LIMIT 1000'''

        rows = self._con.execute(query, args)
        results = []

        for row in rows:
            results.append(PokemonInfo(row[0], row[1], row[2]))

        if len(results) < 3:
            raise MatchError('Not enough results to satisfy constraints')

        choices = list(random.sample(results, 3))

        if weight_sort == 'light-to-heavy':
            choices.sort(key=lambda item: item.weight)
        elif weight_sort == 'heavy-to-light':
            choices.sort(key=lambda item: item.weight)
            choices.reverse()

        return choices


if __name__ == '__main__':
    generator = MatchGenerator(sys.argv[1])
    print(generator.get_match_string(sys.argv[2:]))
