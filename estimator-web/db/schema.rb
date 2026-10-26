# This file is auto-generated from the current state of the database. Instead
# of editing this file, please use the migrations feature of Active Record to
# incrementally modify your database, and then regenerate this schema definition.
#
# This file is the source Rails uses to define your schema when running `bin/rails
# db:schema:load`. When creating a new database, `bin/rails db:schema:load` tends to
# be faster and is potentially less error prone than running all of your
# migrations from scratch. Old migrations may fail to apply correctly if those
# migrations use external dependencies or application code.
#
# It's strongly recommended that you check this file into your version control system.

ActiveRecord::Schema[8.1].define(version: 2026_10_24_120000) do
  # These are extensions that must be enabled in order to support this database
  enable_extension "pg_catalog.plpgsql"

  create_table "chunking_comparisons", force: :cascade do |t|
    t.jsonb "strategies", default: [], null: false
    t.jsonb "queries", default: [], null: false
    t.integer "top_k", default: 3, null: false
    t.string "corpus_label", default: "budgets", null: false
    t.integer "corpus_count", default: 0, null: false
    t.jsonb "response_payload", default: {}, null: false
    t.integer "duration_ms"
    t.datetime "created_at", null: false
    t.datetime "updated_at", null: false
    t.index ["created_at"], name: "index_chunking_comparisons_on_created_at"
  end
end
