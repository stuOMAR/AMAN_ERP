const fs = require('fs');
let content = fs.readFileSync('frontend/src/pages/Stock/PriceLists.jsx', 'utf8');

// 1. Change card margin/padding
content = content.replace('<div className="card">', '<div className="card p-0 m-0 overflow-x-auto">');

// 2. Change modal form field order (Add form)
const addNameGroupPattern = /<div className="form-group">\s*<label>{t\('stock\.price_lists\.modal\.name'\)}<\/label>[\s\S]*?<\/div>/;
const addCurrencyGroupPattern = /<div className="form-group">\s*<label>{t\('stock\.price_lists\.modal\.currency'\)}<\/label>[\s\S]*?<\/div>/;
const addBranchGroupPattern = /<div className="form-group">\s*<label>{t\('stock\.price_lists\.modal\.branch', 'Branch'\)}<\/label>[\s\S]*?<\/div>/;

// Swap Branch and Currency in Add Modal
const formTargetAdd = `<div className="form-group">
                                <label>{t('stock.price_lists.modal.currency')}</label>
                                <select
                                    required
                                    value={formData.currency}
                                    onChange={(e) => setFormData({ ...formData, currency: e.target.value })}
                                    className="form-input"
                                >
                                    <option value="">{t('common.select_currency')}</option>
                                    {currencies.map(c => (
                                        <option key={c.id} value={c.code}>
                                            {c.code} - {c.name}
                                        </option>
                                    ))}
                                </select>
                            </div>

                            <div className="form-group">
                                <label>{t('stock.price_lists.modal.branch', 'Branch')}</label>`;

const formReplacementAdd = `<div className="form-group">
                                <label>{t('common.branch', 'الفرع')}</label>`;

content = content.replace(formTargetAdd, formReplacementAdd);

// Wait, doing this via string replacement manually is tricky if the exact spaces differ.
fs.writeFileSync('patch_temp_output', content);
