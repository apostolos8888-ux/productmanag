# -*- coding: utf-8 -*-
"""
Διαχείριση Προϊόντων — τοπική εφαρμογή Windows.
Python 3.10+ | Tkinter | SQLite (χωρίς εξωτερικές βιβλιοθήκες)
"""
import os
import sys
import shutil
import sqlite3
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from decimal import Decimal, InvalidOperation

APP_NAME = "Διαχείριση Προϊόντων"
APP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "GreekProductManager"
DB_PATH = APP_DIR / "products.db"
IMAGE_DIR = APP_DIR / "images"
PAGE_SIZE = 250

def ensure_dirs():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

def connect_db():
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            price_cents INTEGER NOT NULL CHECK(price_cents >= 0),
            category_id INTEGER NOT NULL REFERENCES categories(id),
            barcode TEXT NOT NULL DEFAULT '',
            image_path TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_products_name ON products(name COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_products_price ON products(price_cents);
        CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode);
        CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
    """)
    return conn

def money_to_cents(value):
    raw = value.strip().replace("€", "").replace(" ", "")
    if "," in raw and "." in raw:
        # Θεωρούμε ότι ο τελευταίος διαχωριστής είναι το δεκαδικό.
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    else:
        raw = raw.replace(",", ".")
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        raise ValueError("Η τιμή δεν είναι έγκυρος αριθμός.")
    if amount < 0:
        raise ValueError("Η τιμή δεν μπορεί να είναι αρνητική.")
    return int((amount * 100).quantize(Decimal("1")))

def cents_to_money(cents):
    return f"{cents / 100:.2f}".replace(".", ",") + " €"

class ProductApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1180x740")
        self.minsize(900, 580)
        self.conn = connect_db()
        self.selected_id = None
        self.selected_image = ""
        self.current_offset = 0
        self.last_query = ""
        self.category_filter = None
        self._setup_style()
        self._build_ui()
        self.refresh_categories()
        self.refresh_products()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def _setup_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("vista")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)
        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="ΔΙΑΧΕΙΡΙΣΗ ΠΡΟΪΟΝΤΩΝ", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="Τοπική βάση δεδομένων • λειτουργεί χωρίς internet").pack(side="right")

        search_frame = ttk.LabelFrame(root, text="Αναζήτηση", padding=8)
        search_frame.pack(fill="x", pady=(0, 10))
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, font=("Segoe UI", 11))
        search_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        search_entry.bind("<Return>", lambda _e: self.search())
        ttk.Button(search_frame, text="Αναζήτηση", command=self.search).pack(side="left", padx=3)
        ttk.Button(search_frame, text="Καθαρισμός", command=self.clear_search).pack(side="left", padx=3)
        ttk.Button(search_frame, text="Όλα τα προϊόντα", command=self.show_all).pack(side="left", padx=3)

        body = ttk.Panedwindow(root, orient="horizontal")
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, padding=(0, 0, 10, 0))
        right = ttk.Frame(body)
        body.add(left, weight=3)
        body.add(right, weight=2)

        cats = ttk.LabelFrame(left, text="Κατηγορίες — πάτησε για φιλτράρισμα", padding=6)
        cats.pack(fill="x", pady=(0, 8))
        self.category_list = tk.Listbox(cats, height=4, exportselection=False, font=("Segoe UI", 10))
        self.category_list.pack(side="left", fill="x", expand=True)
        self.category_list.bind("<<ListboxSelect>>", self.on_category_select)
        cat_scroll = ttk.Scrollbar(cats, orient="vertical", command=self.category_list.yview)
        cat_scroll.pack(side="right", fill="y")
        self.category_list.configure(yscrollcommand=cat_scroll.set)

        list_frame = ttk.LabelFrame(left, text="Προϊόντα (κύλιση με τη ροδέλα ή τη μπάρα)", padding=6)
        list_frame.pack(fill="both", expand=True)
        columns = ("name", "price", "category", "barcode")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("name", text="Ονομασία", command=lambda: self.sort_by("name"))
        self.tree.heading("price", text="Τιμή", command=lambda: self.sort_by("price"))
        self.tree.heading("category", text="Κατηγορία")
        self.tree.heading("barcode", text="Barcode")
        self.tree.column("name", width=220, minwidth=120)
        self.tree.column("price", width=90, anchor="e")
        self.tree.column("category", width=130)
        self.tree.column("barcode", width=130)
        ybar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        xbar = ttk.Scrollbar(list_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self.on_product_select)
        self.tree.bind("<Double-1>", self.on_product_select)

        nav = ttk.Frame(left)
        nav.pack(fill="x", pady=(6, 0))
        self.count_label = ttk.Label(nav, text="0 προϊόντα")
        self.count_label.pack(side="left")
        ttk.Button(nav, text="Προηγούμενα", command=self.prev_page).pack(side="right", padx=(4, 0))
        ttk.Button(nav, text="Επόμενα", command=self.next_page).pack(side="right")

        form = ttk.LabelFrame(right, text="Στοιχεία προϊόντος", padding=12)
        form.pack(fill="both", expand=True)
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Ονομασία *").grid(row=0, column=0, sticky="w", pady=5)
        self.name_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.name_var).grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Label(form, text="Τιμή (€) *").grid(row=1, column=0, sticky="w", pady=5)
        self.price_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.price_var).grid(row=1, column=1, sticky="ew", pady=5)
        ttk.Label(form, text="Κατηγορία *").grid(row=2, column=0, sticky="w", pady=5)
        self.category_var = tk.StringVar()
        self.category_combo = ttk.Combobox(form, textvariable=self.category_var)
        self.category_combo.grid(row=2, column=1, sticky="ew", pady=5)
        ttk.Label(form, text="Barcode").grid(row=3, column=0, sticky="w", pady=5)
        self.barcode_var = tk.StringVar()
        barcode_entry = ttk.Entry(form, textvariable=self.barcode_var)
        barcode_entry.grid(row=3, column=1, sticky="ew", pady=5)
        barcode_entry.bind("<Return>", lambda _e: self.lookup_barcode())
        ttk.Label(form, text="Εικόνα").grid(row=4, column=0, sticky="nw", pady=5)
        image_row = ttk.Frame(form)
        image_row.grid(row=4, column=1, sticky="ew", pady=5)
        self.image_label = ttk.Label(image_row, text="Δεν έχει επιλεγεί εικόνα", wraplength=230)
        self.image_label.pack(side="left", fill="x", expand=True)
        ttk.Button(image_row, text="Επιλογή…", command=self.choose_image).pack(side="right")
        ttk.Label(form, text="* Υποχρεωτικά πεδία").grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 12))
        actions = ttk.Frame(form)
        actions.grid(row=6, column=0, columnspan=2, sticky="ew")
        ttk.Button(actions, text="Νέο / Καθαρισμός", command=self.new_product).pack(fill="x", pady=3)
        ttk.Button(actions, text="Αποθήκευση προϊόντος", style="Accent.TButton", command=self.save_product).pack(fill="x", pady=3)
        ttk.Button(actions, text="Διαγραφή επιλεγμένου", command=self.delete_product).pack(fill="x", pady=3)
        ttk.Button(actions, text="Νέα κατηγορία", command=self.add_category).pack(fill="x", pady=3)
        ttk.Button(actions, text="Εξαγωγή CSV", command=self.export_csv).pack(fill="x", pady=3)
        ttk.Button(actions, text="Αντίγραφο ασφαλείας", command=self.backup_database).pack(fill="x", pady=3)
        self.status_var = tk.StringVar(value=f"Βάση δεδομένων: {DB_PATH}")
        ttk.Label(root, textvariable=self.status_var, foreground="#555").pack(fill="x", pady=(8, 0))

    def refresh_categories(self):
        rows = self.conn.execute("SELECT id, name FROM categories ORDER BY name COLLATE NOCASE").fetchall()
        self.categories = {row["name"]: row["id"] for row in rows}
        current = self.category_var.get() if hasattr(self, "category_var") else ""
        if hasattr(self, "category_combo"):
            self.category_combo["values"] = list(self.categories.keys())
            self.category_var.set(current if current in self.categories else "")
        self.category_list.delete(0, tk.END)
        self.category_list.insert(tk.END, "Όλες οι κατηγορίες")
        for name in self.categories:
            self.category_list.insert(tk.END, name)

    def refresh_products(self, query=None, offset=0):
        self.current_offset = max(0, offset)
        self.last_query = self.search_var.get().strip() if query is None else query
        for item in self.tree.get_children():
            self.tree.delete(item)
        where, params = [], []
        q = self.last_query
        if q:
            # Η αναζήτηση περιλαμβάνει ονομασία, barcode, κατηγορία και τιμή.
            price_query = q.replace(",", ".").replace("€", "").strip()
            search_sql = """(p.name LIKE ? COLLATE NOCASE OR p.barcode LIKE ?
                         OR c.name LIKE ? COLLATE NOCASE OR CAST(p.price_cents AS TEXT) LIKE ?
                         OR printf('%.2f', p.price_cents / 100.0) LIKE ?"""
            params.extend([f"%{q}%", f"%{q}%", f"%{q}%", f"%{price_query.replace('.', '')}%", f"%{price_query}%"])
            # Πρόσθετη σύγκριση ακριβούς τιμής, χωρίς να αποκλείονται barcode/ονόματα.
            try:
                cents = money_to_cents(q)
                search_sql += " OR p.price_cents = ?"
                params.append(cents)
            except ValueError:
                pass
            where.append(search_sql + ")")
        if self.category_filter is not None:
            where.append("p.category_id = ?")
            params.append(self.category_filter)
        clause = (" WHERE " + " AND ".join(where)) if where else ""
        total = self.conn.execute(
            "SELECT COUNT(*) FROM products p JOIN categories c ON c.id=p.category_id" + clause, params
        ).fetchone()[0]
        rows = self.conn.execute(
            """SELECT p.id,p.name,p.price_cents,p.barcode,c.name AS category
               FROM products p JOIN categories c ON c.id=p.category_id"""
            + clause + " ORDER BY p.name COLLATE NOCASE LIMIT ? OFFSET ?",
            params + [PAGE_SIZE, self.current_offset]
        ).fetchall()
        for row in rows:
            self.tree.insert("", "end", iid=str(row["id"]), values=(
                row["name"], cents_to_money(row["price_cents"]), row["category"], row["barcode"]
            ))
        shown_start = self.current_offset + 1 if total else 0
        shown_end = min(self.current_offset + len(rows), total)
        self.count_label.config(text=f"{total:,} προϊόντα • εμφάνιση {shown_start:,}–{shown_end:,}".replace(",", "."))
        self.status_var.set(f"Βάση: {DB_PATH}  |  Σύνολο: {total:,} προϊόντα".replace(",", "."))

    def search(self):
        self.category_filter = None
        self.category_list.selection_clear(0, tk.END)
        self.refresh_products(offset=0)

    def clear_search(self):
        self.search_var.set("")
        self.category_filter = None
        self.category_list.selection_clear(0, tk.END)
        self.refresh_products(offset=0)

    def show_all(self):
        self.search_var.set("")
        self.category_filter = None
        self.category_list.selection_clear(0, tk.END)
        self.refresh_products(query="", offset=0)

    def on_category_select(self, _event=None):
        selected = self.category_list.curselection()
        if not selected:
            return
        index = selected[0]
        if index == 0:
            self.category_filter = None
        else:
            name = self.category_list.get(index)
            self.category_filter = self.categories.get(name)
        self.refresh_products(offset=0)

    def on_product_select(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        product_id = int(selected[0])
        row = self.conn.execute("""
            SELECT p.*, c.name AS category FROM products p
            JOIN categories c ON c.id=p.category_id WHERE p.id=?
        """, (product_id,)).fetchone()
        if not row:
            return
        self.selected_id = product_id
        self.name_var.set(row["name"])
        self.price_var.set(f"{row['price_cents']/100:.2f}".replace(".", ","))
        self.category_var.set(row["category"])
        self.barcode_var.set(row["barcode"])
        self.selected_image = row["image_path"]
        self.image_label.config(text=Path(self.selected_image).name if self.selected_image else "Δεν έχει επιλεγεί εικόνα")

    def choose_image(self):
        path = filedialog.askopenfilename(
            title="Επιλογή εικόνας προϊόντος",
            filetypes=[("Εικόνες", "*.png *.jpg *.jpeg *.gif *.bmp *.webp"), ("Όλα τα αρχεία", "*.*")]
        )
        if not path:
            return
        try:
            src = Path(path)
            safe_name = f"product_{self.selected_id or 'new'}_{abs(hash(str(src.resolve())))}{src.suffix.lower()}"
            dest = IMAGE_DIR / safe_name
            if src.resolve() != dest.resolve():
                shutil.copy2(src, dest)
            self.selected_image = str(dest)
            self.image_label.config(text=src.name)
        except OSError as exc:
            messagebox.showerror("Σφάλμα εικόνας", f"Δεν ήταν δυνατή η αντιγραφή της εικόνας:\n{exc}")

    def save_product(self):
        name = self.name_var.get().strip()
        category = self.category_var.get().strip()
        barcode = self.barcode_var.get().strip()
        if not name or not category:
            messagebox.showwarning("Ελλιπή στοιχεία", "Συμπλήρωσε ονομασία και κατηγορία.")
            return
        try:
            cents = money_to_cents(self.price_var.get())
        except ValueError as exc:
            messagebox.showwarning("Μη έγκυρη τιμή", str(exc))
            return
        try:
            self.conn.execute("INSERT OR IGNORE INTO categories(name) VALUES(?)", (category,))
            category_id = self.conn.execute("SELECT id FROM categories WHERE name=? COLLATE NOCASE", (category,)).fetchone()[0]
            if barcode:
                duplicate = self.conn.execute("SELECT id,name FROM products WHERE barcode=? AND id IS NOT ?", (barcode, self.selected_id)).fetchone()
                if duplicate:
                    if not messagebox.askyesno("Διπλό barcode", f"Το barcode υπάρχει ήδη στο προϊόν «{duplicate['name']}». Να συνεχίσω;"):
                        return
            if self.selected_id:
                self.conn.execute("""UPDATE products SET name=?,price_cents=?,category_id=?,barcode=?,image_path=?,updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                    (name, cents, category_id, barcode, self.selected_image, self.selected_id))
            else:
                self.conn.execute("""INSERT INTO products(name,price_cents,category_id,barcode,image_path) VALUES(?,?,?,?,?)""",
                    (name, cents, category_id, barcode, self.selected_image))
            self.conn.commit()
            self.refresh_categories()
            self.refresh_products(offset=0)
            self.new_product()
            self.status_var.set("Το προϊόν αποθηκεύτηκε.")
        except sqlite3.Error as exc:
            messagebox.showerror("Σφάλμα βάσης δεδομένων", str(exc))

    def new_product(self):
        self.selected_id = None
        self.selected_image = ""
        self.name_var.set("")
        self.price_var.set("")
        self.category_var.set("")
        self.barcode_var.set("")
        self.image_label.config(text="Δεν έχει επιλεγεί εικόνα")
        self.tree.selection_remove(self.tree.selection())

    def delete_product(self):
        if not self.selected_id:
            messagebox.showinfo("Διαγραφή", "Επίλεξε πρώτα ένα προϊόν από τη λίστα.")
            return
        if not messagebox.askyesno("Επιβεβαίωση", "Να διαγραφεί οριστικά το επιλεγμένο προϊόν;"):
            return
        self.conn.execute("DELETE FROM products WHERE id=?", (self.selected_id,))
        self.conn.commit()
        self.new_product()
        self.refresh_products()
        self.refresh_categories()

    def add_category(self):
        win = tk.Toplevel(self)
        win.title("Νέα κατηγορία")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()
        frame = ttk.Frame(win, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Όνομα κατηγορίας:").pack(anchor="w")
        value = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=value, width=34)
        entry.pack(fill="x", pady=8)
        entry.focus_set()
        def save():
            name = value.get().strip()
            if not name:
                messagebox.showwarning("Κατηγορία", "Γράψε όνομα κατηγορίας.", parent=win)
                return
            try:
                self.conn.execute("INSERT INTO categories(name) VALUES(?)", (name,))
                self.conn.commit()
                self.refresh_categories()
                self.category_var.set(name)
                win.destroy()
            except sqlite3.IntegrityError:
                messagebox.showwarning("Κατηγορία", "Η κατηγορία υπάρχει ήδη.", parent=win)
        ttk.Button(frame, text="Αποθήκευση", command=save).pack(fill="x")
        entry.bind("<Return>", lambda _e: save())

    def lookup_barcode(self):
        barcode = self.barcode_var.get().strip()
        if not barcode:
            return
        row = self.conn.execute("""
            SELECT p.id FROM products p WHERE p.barcode=? LIMIT 1
        """, (barcode,)).fetchone()
        if row:
            iid = str(row["id"])
            if self.tree.exists(iid):
                self.tree.selection_set(iid)
                self.tree.see(iid)
                self.on_product_select()
            else:
                self.search_var.set(barcode)
                self.search()
                if self.tree.exists(iid):
                    self.tree.selection_set(iid)
                    self.tree.see(iid)
                    self.on_product_select()
        else:
            self.search_var.set(barcode)
            self.search()

    def prev_page(self):
        self.refresh_products(offset=max(0, self.current_offset - PAGE_SIZE))

    def next_page(self):
        self.refresh_products(offset=self.current_offset + PAGE_SIZE)

    def sort_by(self, field):
        # Η ταξινόμηση στην πρώτη έκδοση γίνεται με την ανανέωση της λίστας.
        if field == "price":
            messagebox.showinfo("Ταξινόμηση", "Η λίστα είναι προς το παρόν ταξινομημένη κατά ονομασία. Η ταξινόμηση κατά τιμή θα προστεθεί σε επόμενη έκδοση.")

    def export_csv(self):
        path = filedialog.asksaveasfilename(title="Εξαγωγή προϊόντων", defaultextension=".csv",
                                            filetypes=[("Αρχείο CSV", "*.csv")], initialfile="proionta.csv")
        if not path:
            return
        import csv
        rows = self.conn.execute("""SELECT p.name,p.price_cents,c.name AS category,p.barcode,p.image_path
            FROM products p JOIN categories c ON c.id=p.category_id ORDER BY p.name COLLATE NOCASE""").fetchall()
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["Ονομασία", "Τιμή (€)", "Κατηγορία", "Barcode", "Διαδρομή εικόνας"])
                for row in rows:
                    writer.writerow([row["name"], f"{row['price_cents']/100:.2f}".replace(".", ","),
                                     row["category"], row["barcode"], row["image_path"]])
            messagebox.showinfo("Εξαγωγή", f"Εξήχθησαν {len(rows)} προϊόντα.")
        except OSError as exc:
            messagebox.showerror("Σφάλμα εξαγωγής", str(exc))

    def backup_database(self):
        path = filedialog.asksaveasfilename(title="Αποθήκευση αντιγράφου ασφαλείας",
            defaultextension=".db", filetypes=[("Βάση SQLite", "*.db")], initialfile="products-backup.db")
        if not path:
            return
        try:
            dest = sqlite3.connect(path)
            self.conn.backup(dest)
            dest.close()
            messagebox.showinfo("Αντίγραφο ασφαλείας", "Το αντίγραφο της βάσης αποθηκεύτηκε.\nΣημείωση: οι εικόνες φυλάσσονται ξεχωριστά στον φάκελο εφαρμογής.")
        except sqlite3.Error as exc:
            messagebox.showerror("Σφάλμα αντιγράφου", str(exc))

    def on_close(self):
        self.conn.close()
        self.destroy()

if __name__ == "__main__":
    try:
        ProductApp().mainloop()
    except Exception as exc:
        messagebox.showerror(APP_NAME, f"Η εφαρμογή αντιμετώπισε σφάλμα:\n{exc}")
