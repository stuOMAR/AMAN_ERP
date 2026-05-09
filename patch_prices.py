import re

file_path = 'frontend/src/pages/Stock/PriceLists.jsx'
with open(file_path, 'r') as f:
    content = f.read()

# 1. Update Card margins
content = content.replace('<div className="card">', '<div className="card p-0 m-0 overflow-hidden">')

# 2. Replace the first modal (Add) manually
def swap_in_modal(text_content):
    # Find currency block exactly
    curr_start = text_content.find('<div className="form-group">\n                                <label>{t(\'stock.price_lists.modal.currency\')}</label>')
    if curr_start == -1: return text_content
    curr_end = text_content.find('</select>\n                            </div>', curr_start) + len('</select>\n                            </div>')
    curr_block = text_content[curr_start:curr_end]
    
    # Find branch block exactly
    branch_start = text_content.find('<div className="form-group">\n                                <label>{t(\'stock.price_lists.modal.branch\', \'Branch\')}</label>', curr_end)
    if branch_start == -1: return text_content
    branch_end = text_content.find('</select>\n                            </div>', branch_start) + len('</select>\n                            </div>')
    branch_block = text_content[branch_start:branch_end]
    
    # Replace translations
    new_branch_block = branch_block.replace("t('stock.price_lists.modal.branch', 'Branch')", "t('common.branch', 'الفرع')")
    
    # Rewrite the text content up to max branch_end
    before = text_content[:curr_start]
    after = text_content[branch_end:]
    middle = text_content[curr_end:branch_start] # Usually just newlines
    
    return before + new_branch_block + middle + curr_block + after

# Swap first modal
content = swap_in_modal(content)

# Swap second modal
content = swap_in_modal(content)

# 3. Add branch_currency option
branch_curr_replace = """<option value="all">{t('common.all_branches', 'جميع الفروع')}</option>}"""
branch_curr_new = """<option value="all">{t('common.all_branches', 'جميع الفروع')}</option>}"""

with open(file_path, 'w') as f:
    f.write(content)
