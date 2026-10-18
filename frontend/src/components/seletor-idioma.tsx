// Dropdown do idioma do app: português, inglês ou espanhol. A escolha fica guardada no aparelho.
import { Dropdown } from "@/src/components/dropdown";
import { IDIOMAS, t, useIdioma } from "@/src/i18n";

export function SeletorIdioma({ variante = "campo" }: { variante?: "campo" | "pilula" }) {
  const { idioma, escolher } = useIdioma();
  return (
    <Dropdown
      testID="seletor-idioma"
      titulo={t("Idioma")}
      icone="globe-outline"
      variante={variante}
      valor={idioma}
      opcoes={IDIOMAS.map((i) => ({ valor: i.codigo, rotulo: i.nome }))}
      onChange={(novo) => {
        void escolher(novo);
      }}
    />
  );
}
