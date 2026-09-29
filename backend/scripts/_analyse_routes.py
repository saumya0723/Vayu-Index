import pandas as pd

df = pd.read_csv('data/official/dgca/processed/dgca_city_pair_passenger_traffic_2024_25.csv')

# Get ranked routes
ranked = df.dropna(subset=['total_bidirectional_passengers']).sort_values(
    'total_bidirectional_passengers', ascending=False).reset_index(drop=True)
ranked['rank'] = ranked.index + 1

print('TOP 30 ROUTES:')
cols = ['rank','city_1_standardized','city_2_standardized',
        'passengers_city1_to_city2','passengers_city2_to_city1','total_bidirectional_passengers']
print(ranked[cols].head(30).to_string())
print()

total_pax = ranked['total_bidirectional_passengers'].sum()
ranked['cumulative_pax'] = ranked['total_bidirectional_passengers'].cumsum()
ranked['cumulative_pct'] = ranked['cumulative_pax'] / total_pax * 100

print('CUMULATIVE COVERAGE:')
for n in [5, 10, 15, 20, 25, 30, 50]:
    top_n = ranked.head(n)
    all_cities = set(top_n['city_1_standardized']) | set(top_n['city_2_standardized'])
    cov = ranked.iloc[n-1]['cumulative_pct']
    print(f'  Top {n:2d}: {cov:.1f}% coverage, {len(all_cities)} distinct cities')

print()
print('Total bidirectional pax (valid routes):', '{:,.0f}'.format(int(total_pax)))
print('Total valid routes:', len(ranked))
