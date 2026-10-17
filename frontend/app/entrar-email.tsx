// Entrar ou criar conta com e-mail e senha — para quem não usa Google (Outlook, Yahoo, iCloud,
// e-mail do trabalho...). Uma tela só, com etapas:
//   entrar → (esqueci → redefinir) · criar → codigo (confirma o e-mail e já entra)
// A conta só passa a existir depois que o código enviado por e-mail confere.

import Ionicons from "@react-native-vector-icons/ionicons";
import { Redirect, useRouter } from "expo-router";
import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Linking,
  Platform,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, ApiError } from "@/src/lib/api";
import { useAuth } from "@/src/lib/auth";
import {
  codigoCompleto,
  limparCodigo,
  Modo,
  textosDoModo,
  validarEmail,
  validarNome,
  validarSenha,
} from "@/src/lib/auth-email";
import { URL_PRIVACIDADE, URL_TERMOS } from "@/src/lib/legal";
import { makeStyles, radius, spacing, useTheme } from "@/src/theme";

const useStyles = makeStyles((c) => ({
  root: { flex: 1, backgroundColor: c.surface },
  headerRow: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  backBtn: { padding: spacing.sm },
  title: { fontSize: 26, fontWeight: "700", color: c.onSurface, paddingHorizontal: spacing.xl },
  subtitle: { fontSize: 14, color: c.muted, paddingHorizontal: spacing.xl, marginTop: 4, marginBottom: spacing.lg, lineHeight: 20 },
  field: { paddingHorizontal: spacing.xl, marginBottom: spacing.lg },
  label: { fontSize: 13, fontWeight: "700", color: c.onSurface, marginBottom: spacing.sm },
  inputRow: { flexDirection: "row", alignItems: "center" },
  input: {
    flex: 1,
    height: 48,
    borderRadius: radius.md,
    backgroundColor: c.surfaceSecondary,
    borderWidth: 1,
    borderColor: c.border,
    paddingHorizontal: spacing.md,
    fontSize: 15,
    color: c.onSurfaceSecondary,
  },
  codigoInput: { fontSize: 24, letterSpacing: 8, textAlign: "center", fontWeight: "700" },
  toggleSenha: { position: "absolute", right: spacing.md, padding: spacing.xs },
  hint: { fontSize: 12, color: c.muted, marginTop: spacing.xs },
  aviso: { fontSize: 13, color: c.onSurface, backgroundColor: c.surfaceTertiary, marginHorizontal: spacing.xl, marginBottom: spacing.lg, padding: spacing.md, borderRadius: radius.md, lineHeight: 18 },
  erro: { fontSize: 13, color: c.error, marginHorizontal: spacing.xl, marginBottom: spacing.lg, lineHeight: 18, fontWeight: "600" },
  cta: { marginHorizontal: spacing.xl, height: 52, borderRadius: radius.md, backgroundColor: c.brand, alignItems: "center", justifyContent: "center" },
  ctaDisabled: { opacity: 0.5 },
  ctaText: { color: c.onBrand, fontSize: 16, fontWeight: "700" },
  link: { alignSelf: "center", paddingVertical: spacing.md, paddingHorizontal: spacing.lg },
  linkText: { fontSize: 14, color: c.onSurface, textDecorationLine: "underline" },
  legal: { marginTop: spacing.md, paddingHorizontal: spacing.xl, fontSize: 12, color: c.muted, textAlign: "center", lineHeight: 18 },
}));

export default function EntrarEmail() {
  const auth = useAuth();
  const router = useRouter();
  const styles = useStyles();
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();

  const [modo, setModo] = useState<Modo>("entrar");
  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [codigo, setCodigo] = useState("");
  const [mostrarSenha, setMostrarSenha] = useState(false);
  const [carregando, setCarregando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);

  if (auth.status === "authenticated") return <Redirect href="/" />;

  const textos = textosDoModo(modo);
  const emailLimpo = email.trim();

  const irPara = (novo: Modo, mensagem: string | null = null) => {
    setModo(novo);
    setErro(null);
    setAviso(mensagem);
  };

  /** Roda uma ação do servidor: bloqueia o botão, mostra a mensagem de erro dele (em português). */
  const executar = async (acao: () => Promise<void>) => {
    setErro(null);
    setCarregando(true);
    try {
      await acao();
    } catch (e) {
      setErro(e instanceof ApiError ? e.message : "Sem conexão com o servidor. Confira a internet e tente de novo.");
    } finally {
      setCarregando(false);
    }
  };

  const post = <T,>(rota: string, corpo: object) =>
    api<T>(`/api/auth/email/${rota}`, { method: "POST", body: JSON.stringify(corpo) });

  const enviarCadastro = () =>
    post("cadastro", { name: nome.trim(), email: emailLimpo, password: senha });

  const acaoPrincipal = () =>
    executar(async () => {
      if (modo === "entrar") {
        const invalido = validarEmail(email) ?? (senha ? null : "Informe a senha.");
        if (invalido) return setErro(invalido);
        const r = await post<{ session_token: string }>("login", { email: emailLimpo, password: senha });
        await auth.signInWithToken(r.session_token);
      } else if (modo === "criar") {
        const invalido = validarNome(nome) ?? validarEmail(email) ?? validarSenha(senha, email);
        if (invalido) return setErro(invalido);
        await enviarCadastro();
        setCodigo("");
        irPara("codigo", `Enviamos um código de 6 dígitos para ${emailLimpo}. Ele vale 10 minutos. Olhe também a caixa de spam.`);
      } else if (modo === "codigo") {
        if (!codigoCompleto(codigo)) return setErro("Digite os 6 dígitos do código.");
        const r = await post<{ session_token: string }>("verificar", { email: emailLimpo, code: codigo });
        await auth.signInWithToken(r.session_token);
      } else if (modo === "esqueci") {
        const invalido = validarEmail(email);
        if (invalido) return setErro(invalido);
        await post("esqueci", { email: emailLimpo });
        setCodigo("");
        setSenha("");
        irPara("redefinir", `Se existir uma conta com ${emailLimpo}, enviamos um código de 6 dígitos para esse e-mail.`);
      } else {
        const invalido = codigoCompleto(codigo) ? validarSenha(senha, email) : "Digite os 6 dígitos do código.";
        if (invalido) return setErro(invalido);
        await post("redefinir", { email: emailLimpo, code: codigo, new_password: senha });
        setSenha("");
        setCodigo("");
        irPara("entrar", "Senha alterada! Entre com a nova senha.");
      }
    });

  const reenviar = () =>
    executar(async () => {
      if (modo === "codigo") await enviarCadastro();
      else await post("esqueci", { email: emailLimpo });
      setAviso("Enviamos um novo código. Pode levar alguns minutos para chegar.");
    });

  const voltar = () => (router.canGoBack() ? router.back() : router.replace("/welcome"));

  const campoSenha = (rotulo: string, autoComplete: "password" | "new-password") => (
    <View style={styles.field}>
      <Text style={styles.label}>{rotulo}</Text>
      <View style={styles.inputRow}>
        <TextInput
          testID="senha-input"
          value={senha}
          onChangeText={setSenha}
          secureTextEntry={!mostrarSenha}
          autoCapitalize="none"
          autoCorrect={false}
          autoComplete={autoComplete}
          textContentType={autoComplete === "password" ? "password" : "newPassword"}
          placeholder={autoComplete === "new-password" ? "Mínimo 8 caracteres" : "Sua senha"}
          placeholderTextColor={colors.muted}
          style={styles.input}
        />
        <Pressable
          testID="mostrar-senha"
          onPress={() => setMostrarSenha((v) => !v)}
          style={styles.toggleSenha}
          accessibilityLabel={mostrarSenha ? "Ocultar senha" : "Mostrar senha"}
        >
          <Ionicons name={mostrarSenha ? "eye-off-outline" : "eye-outline"} size={20} color={colors.muted} />
        </Pressable>
      </View>
    </View>
  );

  const campoCodigo = (
    <View style={styles.field}>
      <Text style={styles.label}>Código de 6 dígitos</Text>
      <TextInput
        testID="codigo-input"
        value={codigo}
        onChangeText={(v) => setCodigo(limparCodigo(v))}
        keyboardType="number-pad"
        maxLength={7}
        autoComplete="one-time-code"
        textContentType="oneTimeCode"
        placeholder="000000"
        placeholderTextColor={colors.muted}
        style={[styles.input, styles.codigoInput]}
      />
    </View>
  );

  const campoEmail = (
    <View style={styles.field}>
      <Text style={styles.label}>E-mail</Text>
      <TextInput
        testID="email-input"
        value={email}
        onChangeText={setEmail}
        keyboardType="email-address"
        autoCapitalize="none"
        autoCorrect={false}
        autoComplete="email"
        textContentType="emailAddress"
        placeholder="voce@exemplo.com"
        placeholderTextColor={colors.muted}
        editable={modo !== "codigo" && modo !== "redefinir"}
        style={[styles.input, (modo === "codigo" || modo === "redefinir") && { opacity: 0.6 }]}
      />
    </View>
  );

  return (
    <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
      <View style={[styles.root, { paddingTop: insets.top }]} testID="entrar-email-screen">
        <View style={styles.headerRow}>
          <Pressable testID="voltar" onPress={voltar} style={styles.backBtn}>
            <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
          </Pressable>
        </View>
        <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ paddingBottom: insets.bottom + spacing.xxl }}>
          <Text style={styles.title}>{textos.titulo}</Text>
          <Text style={styles.subtitle}>{textos.subtitulo}</Text>

          {modo === "criar" ? (
            <View style={styles.field}>
              <Text style={styles.label}>Nome</Text>
              <TextInput
                testID="nome-input"
                value={nome}
                onChangeText={setNome}
                autoCapitalize="words"
                autoComplete="name"
                textContentType="name"
                placeholder="Como você quer ser chamado"
                placeholderTextColor={colors.muted}
                style={styles.input}
              />
            </View>
          ) : null}
          {modo !== "codigo" && modo !== "redefinir" ? campoEmail : null}
          {modo === "codigo" || modo === "redefinir" ? campoCodigo : null}
          {modo === "entrar" ? campoSenha("Senha", "password") : null}
          {modo === "criar" ? campoSenha("Senha", "new-password") : null}
          {modo === "redefinir" ? campoSenha("Nova senha", "new-password") : null}

          {aviso ? <Text style={styles.aviso} testID="aviso">{aviso}</Text> : null}
          {erro ? <Text style={styles.erro} testID="erro">{erro}</Text> : null}

          <Pressable
            testID="acao-principal"
            onPress={acaoPrincipal}
            disabled={carregando}
            style={[styles.cta, carregando && styles.ctaDisabled]}
          >
            {carregando ? <ActivityIndicator color={colors.onBrand} /> : <Text style={styles.ctaText}>{textos.botao}</Text>}
          </Pressable>

          {modo === "entrar" ? (
            <>
              <Pressable testID="ir-esqueci" onPress={() => irPara("esqueci")} style={styles.link}>
                <Text style={styles.linkText}>Esqueci minha senha</Text>
              </Pressable>
              <Pressable testID="ir-criar" onPress={() => irPara("criar")} style={styles.link}>
                <Text style={styles.linkText}>Ainda não tem conta? Criar conta</Text>
              </Pressable>
            </>
          ) : null}
          {modo === "criar" ? (
            <>
              <Pressable testID="ir-entrar" onPress={() => irPara("entrar")} style={styles.link}>
                <Text style={styles.linkText}>Já tem conta? Entrar</Text>
              </Pressable>
              <Text style={styles.legal}>
                Ao criar a conta você concorda com os{" "}
                <Text style={styles.linkText} onPress={() => Linking.openURL(URL_TERMOS)}>
                  termos de uso
                </Text>{" "}
                e a{" "}
                <Text style={styles.linkText} onPress={() => Linking.openURL(URL_PRIVACIDADE)}>
                  política de privacidade
                </Text>
                .
              </Text>
            </>
          ) : null}
          {modo === "codigo" || modo === "redefinir" ? (
            <>
              <Pressable testID="reenviar" onPress={reenviar} disabled={carregando} style={styles.link}>
                <Text style={styles.linkText}>Não chegou? Enviar outro código</Text>
              </Pressable>
              <Pressable
                testID="trocar-email"
                onPress={() => irPara(modo === "codigo" ? "criar" : "esqueci")}
                style={styles.link}
              >
                <Text style={styles.linkText}>Usar outro e-mail</Text>
              </Pressable>
            </>
          ) : null}
          {modo === "esqueci" ? (
            <Pressable testID="ir-entrar" onPress={() => irPara("entrar")} style={styles.link}>
              <Text style={styles.linkText}>Voltar para entrar</Text>
            </Pressable>
          ) : null}
        </ScrollView>
      </View>
    </KeyboardAvoidingView>
  );
}
