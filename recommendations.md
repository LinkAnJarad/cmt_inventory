## 📋 Combined Technical Review Notes

### I. General System Requirements & Reporting

* The system must generate both **transactional reports** and **MIS reports** (for management decision-making).
* Reports should include:
    * **Inventory status report**
    * **Master list report**
    * **Stock movement report**
    * **Report on items with high/low turnover**
    * **Stock-in/stock-out report**
    * **Inventory audit trail report**
* Basic functions like **sorting and filtering** are essential for summarizing data.
* Reports should be **system-generated** with minimal human intervention to maintain **data integrity** and reduce errors.
* An **LIS** (Laboratory Information System) should streamline manual record-keeping by converting it to electronic forms and automating **inventory tracking** and statistics on equipment and consumables usage.

---

### II. Key Modules and Features

| Feature | Requirement / Recommendation |
| :--- | :--- |
| **Notification & Alerts** | Monitor status of laboratory equipment/apparatus, including **operational, calibration, and maintenance status.** |
| **Data Visualization** | This is a key feature. It must support **progressive data accumulation** to generate insights from current and **historical trends**. Analytics should support **long-term monitoring, forecasting, and decision-making**. The system should include **well-designed dashboards** and reports. |
| **Authentication** | User authentication must be explicitly input with a **secure authentication mechanism** to highlight the importance of **data security** and **controlled access** to records. |
| **Reports for Budgeting** | Generate reports that support budgeting, such as **monthly or semester-based consumption** summaries for the Dean. |
| **Barcode/Tagging** | Integrate a **barcode-based tracking feature** for both equipment and consumable items to reduce turnaround time and lessen manual logging errors. |

---

### III. Technical Review Panel Member 2 Recommendations

1.  Include a **Maintenance Table** for the laboratory equipment.
2.  Provide **report generation by category**.
3.  Include **barcode tagging** for the equipment and others.
4.  Include **backup for data recovery**.
5.  Include **aging/expiration notification**.
