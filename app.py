import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, session
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Cargar variables de entorno (.env)
load_dotenv()

# -----------------------
# CONFIGURACIÓN BÁSICA
# -----------------------
app = Flask(__name__)
app.config['SECRET_KEY'] = 'cambia-esta-clave-por-una-muy-larga'

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Formatos permitidos (ampliado)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'}

# URL de la base de datos PostgreSQL (Render)
DATABASE_URL = os.getenv("DATABASE_URL")


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# -----------------------
# CONEXIÓN A LA BD
# -----------------------
def get_db():
    """
    Conecta a PostgreSQL usando DATABASE_URL.
    """
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL no está definida. "
            "Créala en .env con tu External Database URL de Render."
        )
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn


def init_db():
    """
    Crea tablas en PostgreSQL si no existen
    y llena la tabla de participantes (idempotente).
    """
    conn = get_db()
    c = conn.cursor()

    # Tabla de participantes (quién es, código, y a quién le da regalo)
    c.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            code TEXT NOT NULL,
            gives_to INTEGER,
            FOREIGN KEY(gives_to) REFERENCES participants(id)
        );
    """)

    # Tabla de deseos de regalo (dos opciones, con foto opcional)
    c.execute("""
        CREATE TABLE IF NOT EXISTS wishes (
            id SERIAL PRIMARY KEY,
            participant_id INTEGER UNIQUE NOT NULL,
            wish1 TEXT,
            wish1_img TEXT,
            wish2 TEXT,
            wish2_img TEXT,
            FOREIGN KEY(participant_id) REFERENCES participants(id)
        );
    """)

    # Tabla de comidas
    c.execute("""
        CREATE TABLE IF NOT EXISTS foods (
            id SERIAL PRIMARY KEY,
            person_name TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            image_filename TEXT
        );
    """)

    # -------------------------
    # Insertar participantes
    # -------------------------
    participants = [
        ("Miguel",          "M123", None),
        ("Mamá",            "MA45", None),
        ("Papá Luis",       "PL67", None),
        ("Abuelita María",  "AM89", None),
        ("Luis Consentido", "LC11", None),
        ("Daniela",         "DA22", None),
        ("Efraín",          "EF33", None),
        ("Karla",           "KA44", None),
        ("Mariana",         "MA55", None),
        ("Sandra",          "SA66", None),
        ("Alejandro",       "AL77", None),
        ("Brenda",          "BR88", None),
    ]

    for name, code, gives_to in participants:
        c.execute(
            """
            INSERT INTO participants (name, code, gives_to)
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO NOTHING;
            """,
            (name, code, gives_to)
        )

    # Mapeo: quien le da regalo a quién (por nombre)
    asignaciones = {
        "Miguel":          "Brenda",
        "Mamá":            "Abuelita María",
        "Papá Luis":       "Daniela",
        "Abuelita María":  "Mariana",
        "Luis Consentido": "Miguel",
        "Daniela":         "Mamá",
        "Efraín":          "Sandra",
        "Karla":           "Luis Consentido",
        "Mariana":         "Karla",
        "Sandra":          "Papá Luis",
        "Alejandro":       "Efraín",
        "Brenda":          "Alejandro",
    }

    # Actualizar gives_to usando los nombres
    for giver_name, receiver_name in asignaciones.items():
        c.execute("SELECT id FROM participants WHERE name = %s;", (receiver_name,))
        receiver_row = c.fetchone()
        if receiver_row:
            receiver_id = receiver_row["id"]
            c.execute(
                "UPDATE participants SET gives_to = %s WHERE name = %s;",
                (receiver_id, giver_name)
            )

    conn.commit()
    conn.close()
    print("Base de datos PostgreSQL inicializada / sincronizada.")


# Inicializar la BD si no existe (o sincronizar)
init_db()


# -----------------------
# RUTAS
# -----------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    """
    Esta pantalla sirve tanto para:
    - Ver mi intercambio (next=gift)
    - Mi lista de deseos (next=dashboard)
    """
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, name FROM participants ORDER BY name;")
    participants = c.fetchall()

    # De dónde venimos: ?next=gift o ?next=dashboard
    next_page = request.args.get("next") or request.form.get("next") or "dashboard"

    if request.method == "POST":
        participant_id = request.form.get("participant_id")
        code = request.form.get("code", "").strip()

        c.execute(
            "SELECT * FROM participants WHERE id = %s AND code = %s;",
            (participant_id, code)
        )
        user = c.fetchone()
        conn.close()

        if user:
            session["user_id"] = user["id"]
            # Redirigir según lo que se pidió
            if next_page == "gift":
                return redirect(url_for("gift"))
            else:
                return redirect(url_for("dashboard"))
        else:
            flash("Nombre o código incorrecto. Inténtalo de nuevo.", "danger")
            return redirect(url_for("login", next=next_page))

    conn.close()
    return render_template("login.html", participants=participants)


def get_logged_user():
    user_id = session.get("user_id")
    if not user_id:
        return None

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM participants WHERE id = %s;", (user_id,))
    user = c.fetchone()
    conn.close()
    return user


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("Sesión cerrada.", "info")
    return redirect(url_for("index"))


# --------- MI LISTA DE DESEOS -------------
@app.route("/dashboard", methods=["GET", "POST"])
def dashboard():
    """
    Aquí SOLO se ve y edita la lista de deseos del usuario.
    No muestra a quién le da regalo.
    """
    user = get_logged_user()
    if not user:
        return redirect(url_for("login", next="dashboard"))

    conn = get_db()
    c = conn.cursor()

    # Tus propios deseos de regalo (para que tú los edites)
    c.execute(
        "SELECT * FROM wishes WHERE participant_id = %s;",
        (user["id"],)
    )
    my_wishes = c.fetchone()

    if request.method == "POST":
        # Guardar / actualizar tus deseos
        wish1 = request.form.get("wish1", "").strip()
        wish2 = request.form.get("wish2", "").strip()

        wish1_img_filename = None
        wish2_img_filename = None

        # Manejar foto para deseo 1
        file1 = request.files.get("wish1_img")
        if file1 and file1.filename and allowed_file(file1.filename):
            filename1 = secure_filename(file1.filename)
            wish1_img_filename = f"w1_{user['id']}_{filename1}"
            file1.save(os.path.join(app.config["UPLOAD_FOLDER"], wish1_img_filename))

        # Manejar foto para deseo 2
        file2 = request.files.get("wish2_img")
        if file2 and file2.filename and allowed_file(file2.filename):
            filename2 = secure_filename(file2.filename)
            wish2_img_filename = f"w2_{user['id']}_{filename2}"
            file2.save(os.path.join(app.config["UPLOAD_FOLDER"], wish2_img_filename))

        # Si ya tiene fila en wishes, actualizar; si no, crear
        if my_wishes:
            # mantener nombres de archivo anteriores si no se cargó una nueva foto
            if not wish1_img_filename:
                wish1_img_filename = my_wishes["wish1_img"]
            if not wish2_img_filename:
                wish2_img_filename = my_wishes["wish2_img"]

            c.execute(
                """
                UPDATE wishes
                SET wish1 = %s, wish1_img = %s, wish2 = %s, wish2_img = %s
                WHERE participant_id = %s;
                """,
                (wish1, wish1_img_filename, wish2, wish2_img_filename, user["id"])
            )
        else:
            c.execute(
                """
                INSERT INTO wishes (participant_id, wish1, wish1_img, wish2, wish2_img)
                VALUES (%s, %s, %s, %s, %s);
                """,
                (user["id"], wish1, wish1_img_filename, wish2, wish2_img_filename)
            )

        conn.commit()
        conn.close()
        flash("Tu lista de deseos se guardó correctamente.", "success")
        return redirect(url_for("dashboard"))

    conn.close()

    return render_template(
        "dashboard.html",
        user=user,
        my_wishes=my_wishes
    )


@app.route("/dashboard/delete", methods=["POST"])
def delete_wishes():
    """Borra toda la lista de deseos del usuario (texto y fotos)."""
    user = get_logged_user()
    if not user:
        return redirect(url_for("login", next="dashboard"))

    conn = get_db()
    c = conn.cursor()

    # Buscar nombres de archivos para borrarlos del disco
    c.execute(
        "SELECT wish1_img, wish2_img FROM wishes WHERE participant_id = %s;",
        (user["id"],)
    )
    row = c.fetchone()

    if row:
        for col in ("wish1_img", "wish2_img"):
            filename = row[col]
            if filename:
                path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass

        # Borrar registro de desires
        c.execute(
            "DELETE FROM wishes WHERE participant_id = %s;",
            (user["id"],)
        )
        conn.commit()
        flash("Tu lista de deseos se borró correctamente.", "info")
    else:
        flash("No tenías lista de deseos guardada.", "info")

    conn.close()
    return redirect(url_for("dashboard"))


# --------- VER MI INTERCAMBIO -------------
@app.route("/gift")
def gift():
    """
    Aquí se ve:
    - A quién le das regalo
    - La lista de deseos de esa persona
    """
    user = get_logged_user()
    if not user:
        return redirect(url_for("login", next="gift"))

    conn = get_db()
    c = conn.cursor()

    receiver = None
    receiver_wishes = None

    if user["gives_to"]:
        c.execute(
            "SELECT * FROM participants WHERE id = %s;",
            (user["gives_to"],)
        )
        receiver = c.fetchone()

        if receiver:
            c.execute(
                "SELECT * FROM wishes WHERE participant_id = %s;",
                (receiver["id"],)
            )
            receiver_wishes = c.fetchone()

    conn.close()

    return render_template(
        "gift.html",
        user=user,
        receiver=receiver,
        receiver_wishes=receiver_wishes
    )


# -----------------------
# COMIDAS
# -----------------------
@app.route("/comidas", methods=["GET", "POST"])
def foods():
    user = get_logged_user()

    conn = get_db()
    c = conn.cursor()

    if request.method == "POST":
        person_name = request.form.get("person_name", "").strip()
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()

        if not person_name:
            person_name = user["name"] if user else "Invitado"

        img_filename = None
        file = request.files.get("food_img")
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            img_filename = f"food_{person_name}_{filename}"
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], img_filename))

        if title:
            c.execute(
                """
                INSERT INTO foods (person_name, title, description, image_filename)
                VALUES (%s, %s, %s, %s);
                """,
                (person_name, title, description, img_filename)
            )
            conn.commit()
            flash("Comida registrada para la cena de Navidad.", "success")
        else:
            flash("El título de la comida es obligatorio.", "danger")

        conn.close()
        return redirect(url_for("foods"))

    c.execute("SELECT * FROM foods ORDER BY id DESC;")
    foods_list = c.fetchall()
    conn.close()

    return render_template("foods.html", foods_list=foods_list, user=user)


@app.route("/comidas/editar/<int:food_id>", methods=["GET", "POST"])
def edit_food(food_id):
    """Editar un platillo existente."""
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM foods WHERE id = %s;", (food_id,))
    food = c.fetchone()

    if not food:
        conn.close()
        flash("Platillo no encontrado.", "danger")
        return redirect(url_for("foods"))

    if request.method == "POST":
        person_name = request.form.get("person_name", "").strip() or food["person_name"]
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()

        if not title:
            conn.close()
            flash("El nombre del platillo es obligatorio.", "danger")
            return redirect(url_for("edit_food", food_id=food_id))

        img_filename = food["image_filename"]

        file = request.files.get("food_img")
        if file and file.filename and allowed_file(file.filename):
            # borrar foto anterior si existe
            if img_filename:
                old_path = os.path.join(app.config["UPLOAD_FOLDER"], img_filename)
                if os.path.exists(old_path):
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass

            filename = secure_filename(file.filename)
            img_filename = f"food_{person_name}_{filename}"
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], img_filename))

        c.execute(
            """
            UPDATE foods
            SET person_name = %s, title = %s, description = %s, image_filename = %s
            WHERE id = %s;
            """,
            (person_name, title, description, img_filename, food_id)
        )
        conn.commit()
        conn.close()

        flash("Platillo actualizado correctamente.", "success")
        return redirect(url_for("foods"))

    conn.close()
    return render_template("foods_edit.html", food=food)


@app.route("/comidas/eliminar/<int:food_id>", methods=["POST"])
def delete_food(food_id):
    """Eliminar un platillo (y su imagen si existe)."""
    conn = get_db()
    c = conn.cursor()

    # Buscar la imagen para borrarla del disco
    c.execute("SELECT image_filename FROM foods WHERE id = %s;", (food_id,))
    row = c.fetchone()
    if row and row["image_filename"]:
        img_path = os.path.join(app.config["UPLOAD_FOLDER"], row["image_filename"])
        if os.path.exists(img_path):
            try:
                os.remove(img_path)
            except OSError:
                pass  # si falla, no pasa nada grave

    # Borrar el registro de la BD
    c.execute("DELETE FROM foods WHERE id = %s;", (food_id,))
    conn.commit()
    conn.close()

    flash("Platillo eliminado.", "info")
    return redirect(url_for("foods"))


# -----------------------
# MAIN
# -----------------------
if __name__ == "__main__":
    app.run(debug=True)
