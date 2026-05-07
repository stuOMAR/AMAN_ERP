const ERROR_CODES = {
  // Auth errors
  'auth.invalid_credentials': { en: 'Invalid email or password', ar: 'بريد إلكتروني أو كلمة مرور غير صالحة' },
  'auth.token_expired': { en: 'Session expired, please login again', ar: 'انتهت الجلسة، يرجى تسجيل الدخول مرة أخرى' },
  'auth.token_invalid': { en: 'Invalid or tampered token', ar: 'رمز غير صالح أو تم التلاعب به' },
  'auth.token_consumed': { en: 'This link has already been used', ar: 'تم استخدام هذا الرابط بالفعل' },
  'auth.insufficient_permissions': { en: 'You do not have permission for this action', ar: 'ليس لديك صلاحية لهذا الإجراء' },

  // Validation errors
  'validation.required_field': { en: 'This field is required', ar: 'هذا الحقل مطلوب' },
  'validation.invalid_format': { en: 'Invalid format', ar: 'تنسيق غير صالح' },
  'validation.duplicate_entry': { en: 'This entry already exists', ar: 'هذا الإدخال موجود بالفعل' },

  // Cache errors
  'cache.unavailable': { en: 'Service temporarily unavailable', ar: 'الخدمة غير متاحة مؤقتاً' },

  // Business errors
  'business.insufficient_balance': { en: 'Insufficient balance', ar: 'رصيد غير كافٍ' },
  'business.period_closed': { en: 'This period is closed', ar: 'هذه الفترة مغلقة' },
  'business.negative_inventory': { en: 'Insufficient inventory', ar: 'مخزون غير كافٍ' },

  // POS errors
  'pos.stock_lock_conflict': { en: 'Stock lock conflict — another transaction is in progress', ar: 'تعارض في قفل المخزون — معاملة أخرى قيد التنفيذ' },

  // DMS errors
  'dms.quota_exceeded': { en: 'Storage quota exceeded', ar: 'تم تجاوز حد التخزين' },
  'dms.mime_mismatch': { en: 'File type does not match the declared type', ar: 'نوع الملف لا يتطابق مع النوع المصرح به' },
  'dms.quarantined': { en: 'This file has been quarantined for security reasons', ar: 'تم حجر هذا الملف لأسباب أمنية' },

  // FSM errors
  'fsm.zero_revenue_requires_approval': { en: 'Zero-revenue service order requires approval', ar: 'أمر خدمة بدون إيرادات يتطلب موافقة' },

  // Payroll errors
  'payroll.period_overlap': { en: 'Payroll period overlaps with an existing period', ar: 'فترة الرواتب تتداخل مع فترة موجودة' },
  'payroll.duplicate_payslip': { en: 'A payslip already exists for this employee and period', ar: 'قسيمة راتب موجودة بالفعل لهذا الموظف والفترة' },

  // Notification errors
  'notifications.template_missing': { en: 'Notification template not found', ar: 'قالب الإشعار غير موجود' },
  'notifications.dead_letter': { en: 'Notification could not be delivered after multiple attempts', ar: 'لم يتم تسليم الإشعار بعد محاولات متعددة' },

  // Search errors
  'search.registry_empty': { en: 'Search registry not initialized', ar: 'سجل البحث غير مهيأ' },

  // Reconciliation errors
  'reconciliation.drift_exceeded': { en: 'Reconciliation difference exceeds tolerance', ar: 'فرق التسوية يتجاوز الحد المسموح' },

  // Generic
  'server.internal_error': { en: 'An unexpected error occurred', ar: 'حدث خطأ غير متوقع' },
  'network.offline': { en: 'You are offline', ar: 'أنت غير متصل بالإنترنت' },
};

export default ERROR_CODES;

export function getErrorMessage(code, locale = 'en') {
  const entry = ERROR_CODES[code];
  if (!entry) return code;
  return entry[locale] || entry.en || code;
}
