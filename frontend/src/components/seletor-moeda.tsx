// Dropdown da moeda (a lista vem do servidor; o nome de cada moeda segue o idioma do app).
import { Dropdown } from "@/src/components/dropdown";
import { t } from "@/src/i18n";
import { rotuloDaMoeda } from "@/src/lib/moedas";

export function SeletorMoeda({ valor, moedas, onChange }: { valor: string; moedas: string[]; onChange: (m: string) => void }) {
  return (
    <Dropdown
      testID="seletor-moeda"
      titulo={t("Moeda")}
      icone="cash-outline"
      valor={valor}
      opcoes={moedas.map((m) => ({ valor: m, rotulo: rotuloDaMoeda(m) }))}
      onChange={onChange}
    />
  );
}
