class CreateChunkingComparisons < ActiveRecord::Migration[8.1]
  def change
    create_table :chunking_comparisons do |t|
      t.jsonb :strategies, null: false, default: []        # estrategias pedidas
      t.jsonb :queries, null: false, default: []           # consultas pedidas
      t.integer :top_k, null: false, default: 3
      t.string :corpus_label, null: false, default: "budgets"
      t.integer :corpus_count, null: false, default: 0     # presupuestos enviados
      t.jsonb :response_payload, null: false, default: {}  # respuesta completa de POST /embeddings/compare
      t.integer :duration_ms                               # tiempo de la llamada a la API

      t.timestamps
    end
    add_index :chunking_comparisons, :created_at
  end
end
