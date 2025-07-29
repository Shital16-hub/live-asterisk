import os

output_file = 'towing-knowledge.txt'
input_dir = os.path.dirname(os.path.abspath(__file__))

# Get all .txt files in the directory, sorted alphabetically
files = sorted([f for f in os.listdir(input_dir) if f.endswith('.txt') and f != output_file])

with open(os.path.join(input_dir, output_file), 'w', encoding='utf-8') as outfile:
    for fname in files:
        with open(os.path.join(input_dir, fname), 'r', encoding='utf-8') as infile:
            outfile.write(f'===== {fname} =====\n')
            outfile.write(infile.read())
            outfile.write('\n\n')

print(f'Combined {len(files)} files into {output_file}') 