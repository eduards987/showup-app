// Typed API DTOs mirroring backend Pydantic models.

export type Role = "cliente" | "profissional";

export type Servico = {
  servico_id: string;
  profissional_id: string;
  nome: string;
  descricao?: string | null;
  valor_centavos: number;
  taxa_no_show_centavos: number;
  duracao_min: number;
  moeda: string;
  ativo: boolean;
  criado_em: string;
};

export type ProfissionalPublic = {
  user_id: string;
  name: string;
  picture?: string | null;
  categorias: string[];
  servicos_count: number;
};

export type ProfissionalDetail = {
  user_id: string;
  name: string;
  picture?: string | null;
  categorias: string[];
  timezone: string;
  servicos: Servico[];
  // false quando o profissional ainda não habilitou os recebimentos (e o servidor
  // exige isso) — o app avisa em vez de deixar o cliente tentar agendar.
  aceita_agendamentos?: boolean;
  // "mercadopago": o cliente agenda pelo link (página web), com cartão ou Pix do Mercado Pago.
  recebimento?: "stripe" | "mercadopago";
  link_agendamento?: string | null;
  pix_disponivel?: boolean;
};

export type Agendamento = {
  agendamento_id: string;
  profissional_id: string;
  cliente_id: string;
  servico_id: string;
  servico_nome: string;
  profissional_nome: string;
  cliente_nome: string;
  horario_inicio: string;
  horario_fim: string;
  valor_total_centavos: number;
  valor_no_show_centavos: number;
  moeda: string;
  status_agendamento: string;
  status_confirmacao: "pendente" | "compareceu" | "nao_compareceu" | "sem_resposta";
  payment_intent_id: string;
  hold_status: "autorizado" | "capturado_total" | "capturado_taxa" | "expirado" | "cancelado";
  hold_expira_em: string;
  janela_confirmacao_expira_em: string;
  valor_capturado_centavos: number;
  criado_em: string;
};

export type CardInfo = {
  has_card: boolean;
  brand?: string;
  last4?: string;
  exp_month?: number;
  exp_year?: number;
};
