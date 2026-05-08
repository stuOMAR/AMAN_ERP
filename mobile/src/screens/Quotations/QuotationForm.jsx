/**
 * Quotation Form — create quotation (matches backend QuotationCreate schema).
 */
import React, { useState, useEffect } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, ScrollView,
  StyleSheet, Alert, ActivityIndicator, Modal, FlatList,
} from 'react-native';
import { useNetwork } from '../../../App';
import { quotationAPI, customerAPI, inventoryAPI, taxAPI } from '../../services/api';
import { enqueue } from '../../services/syncService';
import { formatAmount } from '../../utils/formatters';

export default function QuotationForm({ navigation }) {
  const { isConnected } = useNetwork();
  const [customers, setCustomers] = useState([]);
  const [products, setProducts] = useState([]);
  const [selectedCustomer, setSelectedCustomer] = useState(null);
  const defaultTaxRate = branchTax?.tax_rate?.toString() || '';
  const [items, setItems] = useState([{ product_id: null, product_name: '', quantity: '', unit_price: '', tax_rate: defaultTaxRate, discount: '0' }]);
  const [notes, setNotes] = useState('');
  const [loading, setLoading] = useState(false);
  const [dataLoading, setDataLoading] = useState(true);
  const [showCustomerPicker, setShowCustomerPicker] = useState(false);
  const [showProductPicker, setShowProductPicker] = useState(null);
  const [searchText, setSearchText] = useState('');
  const [branchTax, setBranchTax] = useState(null);

  useEffect(() => { loadData(); }, []);

  const loadData = async () => {
    try {
      const [custs, prods] = await Promise.allSettled([
        customerAPI.list({ limit: 500 }),
        inventoryAPI.list({ limit: 500 }),
      ]);
      if (custs.status === 'fulfilled') setCustomers(custs.value || []);
      if (prods.status === 'fulfilled') setProducts(prods.value || []);
      // Fetch default branch tax rate
      try {
        const taxRes = await taxAPI.getBranchTax('default');
        if (taxRes?.tax_rate != null) setBranchTax(taxRes);
      } catch { /* no branch tax available */ }
    } catch { /* ignore */ }
    setDataLoading(false);
  };

  const addLine = () => {
    setItems([...items, { product_id: null, product_name: '', quantity: '', unit_price: '', tax_rate: branchTax?.tax_rate?.toString() || '', discount: '0' }]);
  };
  const updateLine = (index, field, value) => {
    const copy = [...items];
    copy[index] = { ...copy[index], [field]: value };
    setItems(copy);
  };
  const selectProduct = (index, product) => {
    const copy = [...items];
    copy[index] = {
      ...copy[index],
      product_id: product.id,
      product_name: product.name || product.product_name || product.item_name || '',
      unit_price: String(product.selling_price || product.price || '0'),
    };
    setItems(copy);
    setShowProductPicker(null);
    setSearchText('');
  };
  const removeLine = (index) => {
    if (items.length <= 1) return;
    setItems(items.filter((_, i) => i !== index));
  };
  const getLineTotal = (item) => {
    const qty = parseFloat(item.quantity) || 0;
    const price = parseFloat(item.unit_price) || 0;
    const discount = parseFloat(item.discount) || 0;
    const tax = parseFloat(item.tax_rate) || 0;
    const subtotal = qty * price - discount;
    return subtotal + (subtotal * tax / 100);
  };
  const getTotal = () => items.reduce((sum, item) => sum + getLineTotal(item), 0);

  const handleSubmit = async () => {
    if (!selectedCustomer) { Alert.alert('خطأ', 'يرجى اختيار العميل'); return; }
    const validItems = items.filter((i) => i.product_id && i.quantity && i.unit_price);
    if (validItems.length === 0) { Alert.alert('خطأ', 'يرجى إضافة بند واحد على الأقل مع منتج'); return; }
    const today = new Date().toISOString().split('T')[0];
    const payload = {
      customer_id: selectedCustomer.id,
      quotation_date: today,
      notes,
      items: validItems.map((i) => ({
        product_id: i.product_id,
        quantity: parseFloat(i.quantity),
        unit_price: parseFloat(i.unit_price),
        tax_rate: parseFloat(i.tax_rate) || branchTax?.tax_rate || 0,
        discount: parseFloat(i.discount) || 0,
      })),
    };
    setLoading(true);
    try {
      if (isConnected) {
        await quotationAPI.create(payload);
        Alert.alert('تم بنجاح', 'تم إنشاء عرض السعر', [{ text: 'حسنًا', onPress: () => navigation.goBack() }]);
      } else {
        await enqueue('quotation', null, 'create', payload);
        Alert.alert('تم الحفظ محليًا', 'سيتم الإرسال عند استعادة الاتصال', [{ text: 'حسنًا', onPress: () => navigation.goBack() }]);
      }
    } catch (err) {
      Alert.alert('خطأ', err.message || 'حدث خطأ في الإرسال');
    } finally { setLoading(false); }
  };

  const filteredCustomers = customers.filter((c) =>
    !searchText || (c.name || '').includes(searchText) || (c.party_code || '').includes(searchText)
  );
  const filteredProducts = products.filter((p) =>
    !searchText || (p.name || p.product_name || '').includes(searchText) || (p.sku || p.product_code || '').includes(searchText)
  );

  if (dataLoading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color={PRIMARY} />
        <Text style={styles.loadingText}>جارٍ تحميل البيانات...</Text>
      </View>
    );
  }

  return (
    <ScrollView style={styles.container} contentContainerStyle={styles.content}>
      {!isConnected && (
        <View style={styles.offlineBanner}>
          <Text style={styles.bannerText}>⚡ وضع عدم الاتصال — سيتم الحفظ محليًا</Text>
        </View>
      )}

      {/* Customer Selection */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>العميل</Text>
        <TouchableOpacity style={styles.pickerBtn} onPress={() => { setSearchText(''); setShowCustomerPicker(true); }}>
          <Text style={styles.pickerChevron}>‹</Text>
          <Text style={[styles.pickerText, !selectedCustomer && styles.pickerPlaceholder]}>
            {selectedCustomer ? `${selectedCustomer.name} (${selectedCustomer.party_code || ''})` : 'اختر العميل *'}
          </Text>
        </TouchableOpacity>
      </View>

      {/* Line Items */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>البنود</Text>
        {items.map((item, idx) => (
          <View key={idx} style={styles.lineCard}>
            <View style={styles.lineHeader}>
              <TouchableOpacity onPress={() => removeLine(idx)} disabled={items.length <= 1}
                style={[styles.removeBtn, items.length <= 1 && styles.removeBtnHidden]}>
                <Text style={styles.removeBtnText}>حذف ✕</Text>
              </TouchableOpacity>
              <View style={styles.lineNumBadge}><Text style={styles.lineNumText}>بند {idx + 1}</Text></View>
            </View>
            <Text style={styles.label}>المنتج *</Text>
            <TouchableOpacity style={styles.pickerBtn} onPress={() => { setSearchText(''); setShowProductPicker(idx); }}>
              <Text style={styles.pickerChevron}>‹</Text>
              <Text style={[styles.pickerText, !item.product_id && styles.pickerPlaceholder]}>
                {item.product_name || 'اختر المنتج'}
              </Text>
            </TouchableOpacity>
            <View style={styles.threeCol}>
              <View style={styles.col3}>
                <Text style={styles.label}>الكمية</Text>
                <TextInput style={styles.input} placeholder="0" value={item.quantity}
                  onChangeText={(v) => updateLine(idx, 'quantity', v)} keyboardType="numeric" textAlign="right" placeholderTextColor="#90a4ae" />
              </View>
              <View style={styles.col3}>
                <Text style={styles.label}>السعر</Text>
                <TextInput style={styles.input} placeholder="0.00" value={item.unit_price}
                  onChangeText={(v) => updateLine(idx, 'unit_price', v)} keyboardType="numeric" textAlign="right" placeholderTextColor="#90a4ae" />
              </View>
              <View style={styles.col3}>
                <Text style={styles.label}>الضريبة%</Text>
                <TextInput style={styles.input} placeholder={branchTax?.tax_rate?.toString() || '0'} value={item.tax_rate}
                  onChangeText={(v) => updateLine(idx, 'tax_rate', v)} keyboardType="numeric" textAlign="right" placeholderTextColor="#90a4ae" />
              </View>
            </View>
            {item.quantity && item.unit_price ? (
              <View style={styles.lineTotalRow}>
                <Text style={styles.lineTotalValue}>{formatAmount(getLineTotal(item), 'SAR')}</Text>
                <Text style={styles.lineTotalLabel}>المجموع</Text>
              </View>
            ) : null}
          </View>
        ))}
        <TouchableOpacity style={styles.addLineBtn} onPress={addLine}>
          <Text style={styles.addLineBtnText}>+ إضافة بند</Text>
        </TouchableOpacity>
      </View>

      {/* Notes */}
      <View style={styles.section}>
        <Text style={styles.sectionTitle}>ملاحظات</Text>
        <TextInput style={[styles.input, styles.textarea]} value={notes} onChangeText={setNotes}
          placeholder="ملاحظات إضافية (اختياري)" multiline textAlign="right" placeholderTextColor="#90a4ae" textAlignVertical="top" />
      </View>

      {/* Total */}
      <View style={styles.totalCard}>
        <Text style={styles.totalValue}>{formatAmount(getTotal(), 'SAR')}</Text>
        <Text style={styles.totalLabel}>الإجمالي شامل الضريبة</Text>
      </View>

      <TouchableOpacity style={[styles.submitBtn, loading && styles.submitBtnDisabled]} onPress={handleSubmit} disabled={loading}>
        {loading ? <ActivityIndicator color="#fff" size="small" />
          : <Text style={styles.submitText}>{isConnected ? '📤 إرسال عرض السعر' : '💾 حفظ محليًا'}</Text>}
      </TouchableOpacity>

      {/* Customer Picker Modal */}
      <PickerModal visible={showCustomerPicker} title="اختر العميل" data={filteredCustomers}
        searchText={searchText} onSearch={setSearchText}
        onSelect={(c) => { setSelectedCustomer(c); setShowCustomerPicker(false); setSearchText(''); }}
        onClose={() => { setShowCustomerPicker(false); setSearchText(''); }}
        renderItem={(c) => (<View><Text style={styles.modalItemTitle}>{c.name}</Text>
          <Text style={styles.modalItemSub}>{c.party_code} {c.phone ? `• ${c.phone}` : ''}</Text></View>)} />

      {/* Product Picker Modal */}
      <PickerModal visible={showProductPicker !== null} title="اختر المنتج" data={filteredProducts}
        searchText={searchText} onSearch={setSearchText}
        onSelect={(p) => selectProduct(showProductPicker, p)}
        onClose={() => { setShowProductPicker(null); setSearchText(''); }}
        renderItem={(p) => (<View><Text style={styles.modalItemTitle}>{p.name || p.product_name}</Text>
          <Text style={styles.modalItemSub}>{p.sku || p.product_code} • {formatAmount(p.selling_price || 0, 'SAR')}</Text></View>)} />
    </ScrollView>
  );
}

function PickerModal({ visible, title, data, searchText, onSearch, onSelect, onClose, renderItem }) {
  return (
    <Modal visible={visible} animationType="slide" transparent>
      <View style={styles.modalOverlay}>
        <View style={styles.modalContent}>
          <View style={styles.modalHeader}>
            <TouchableOpacity onPress={onClose}><Text style={styles.modalClose}>✕</Text></TouchableOpacity>
            <Text style={styles.modalTitle}>{title}</Text>
          </View>
          <TextInput style={styles.modalSearch} placeholder="بحث..." value={searchText}
            onChangeText={onSearch} textAlign="right" placeholderTextColor="#90a4ae" />
          <FlatList data={data} keyExtractor={(item) => String(item.id)}
            renderItem={({ item }) => (
              <TouchableOpacity style={styles.modalItem} onPress={() => onSelect(item)}>{renderItem(item)}</TouchableOpacity>
            )}
            ListEmptyComponent={<Text style={styles.modalEmpty}>لا توجد نتائج</Text>} />
        </View>
      </View>
    </Modal>
  );
}

const PRIMARY = '#1976d2';

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f0f4f8' },
  content: { paddingBottom: 32 },
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: '#f0f4f8' },
  loadingText: { marginTop: 12, color: '#546e7a', fontSize: 15 },
  offlineBanner: { backgroundColor: '#e65100', padding: 10, alignItems: 'center' },
  bannerText: { color: '#fff', fontWeight: '600', fontSize: 13 },
  section: {
    backgroundColor: '#fff', borderRadius: 12, marginHorizontal: 14,
    marginTop: 14, padding: 16, elevation: 2,
    shadowColor: '#000', shadowOffset: { width: 0, height: 1 }, shadowOpacity: 0.05, shadowRadius: 3,
  },
  sectionTitle: {
    fontSize: 16, fontWeight: '700', color: '#1a2332', textAlign: 'right',
    marginBottom: 14, paddingBottom: 10, borderBottomWidth: 1, borderBottomColor: '#f0f4f8',
  },
  label: { fontSize: 13, fontWeight: '600', color: '#546e7a', textAlign: 'right', marginBottom: 6 },
  input: {
    backgroundColor: '#f8fafc', borderWidth: 1.5, borderColor: '#e0e7ef',
    borderRadius: 10, paddingHorizontal: 14, paddingVertical: 12, fontSize: 15, color: '#1a2332', marginBottom: 12,
  },
  textarea: { minHeight: 90, textAlignVertical: 'top' },
  pickerBtn: {
    flexDirection: 'row-reverse', alignItems: 'center',
    backgroundColor: '#f8fafc', borderWidth: 1.5, borderColor: '#e0e7ef',
    borderRadius: 10, paddingHorizontal: 14, paddingVertical: 14, marginBottom: 12,
  },
  pickerText: { flex: 1, fontSize: 15, color: '#1a2332', textAlign: 'right' },
  pickerPlaceholder: { color: '#90a4ae' },
  pickerChevron: { fontSize: 22, color: '#b0bec5', marginLeft: 8 },
  lineCard: {
    borderWidth: 1, borderColor: '#e0e7ef', borderRadius: 10,
    padding: 12, marginBottom: 12, backgroundColor: '#fafbfe',
  },
  lineHeader: {
    flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10,
  },
  lineNumBadge: { backgroundColor: '#e3f2fd', borderRadius: 16, paddingHorizontal: 10, paddingVertical: 3 },
  lineNumText: { fontSize: 12, fontWeight: '700', color: '#1565c0' },
  removeBtn: { paddingVertical: 3, paddingHorizontal: 8 },
  removeBtnHidden: { opacity: 0 },
  removeBtnText: { fontSize: 12, color: '#c62828', fontWeight: '600' },
  threeCol: { flexDirection: 'row-reverse', gap: 8 },
  col3: { flex: 1 },
  lineTotalRow: {
    flexDirection: 'row-reverse', justifyContent: 'space-between',
    alignItems: 'center', paddingTop: 8, borderTopWidth: 1, borderTopColor: '#e0e7ef',
  },
  lineTotalLabel: { fontSize: 13, color: '#546e7a' },
  lineTotalValue: { fontSize: 16, fontWeight: '700', color: PRIMARY },
  addLineBtn: {
    borderWidth: 1.5, borderColor: PRIMARY, borderStyle: 'dashed',
    borderRadius: 10, paddingVertical: 12, alignItems: 'center',
  },
  addLineBtnText: { color: PRIMARY, fontWeight: '700', fontSize: 15 },
  totalCard: {
    backgroundColor: '#e3f2fd', borderRadius: 12, marginHorizontal: 14,
    marginTop: 14, padding: 16, alignItems: 'center',
  },
  totalLabel: { fontSize: 13, color: '#546e7a', marginTop: 4 },
  totalValue: { fontSize: 24, fontWeight: 'bold', color: PRIMARY },
  submitBtn: {
    backgroundColor: PRIMARY, borderRadius: 12, marginHorizontal: 14,
    marginTop: 20, paddingVertical: 16, alignItems: 'center', elevation: 3,
  },
  submitBtnDisabled: { opacity: 0.65 },
  submitText: { color: '#fff', fontSize: 17, fontWeight: '700' },
  modalOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'flex-end' },
  modalContent: {
    backgroundColor: '#fff', borderTopLeftRadius: 20, borderTopRightRadius: 20,
    maxHeight: '70%', paddingBottom: 30,
  },
  modalHeader: {
    flexDirection: 'row-reverse', justifyContent: 'space-between',
    alignItems: 'center', padding: 16, borderBottomWidth: 1, borderBottomColor: '#f0f4f8',
  },
  modalTitle: { fontSize: 18, fontWeight: '700', color: '#1a2332' },
  modalClose: { fontSize: 20, color: '#90a4ae', padding: 4 },
  modalSearch: {
    margin: 12, backgroundColor: '#f8fafc', borderWidth: 1, borderColor: '#e0e7ef',
    borderRadius: 10, paddingHorizontal: 14, paddingVertical: 10, fontSize: 15, color: '#1a2332',
  },
  modalItem: {
    paddingVertical: 14, paddingHorizontal: 16,
    borderBottomWidth: 1, borderBottomColor: '#f5f7fa',
  },
  modalItemTitle: { fontSize: 15, fontWeight: '600', color: '#1a2332', textAlign: 'right' },
  modalItemSub: { fontSize: 12, color: '#90a4ae', textAlign: 'right', marginTop: 2 },
  modalEmpty: { textAlign: 'center', color: '#90a4ae', padding: 40, fontSize: 15 },
});
