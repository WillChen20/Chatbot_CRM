import streamlit as st
import google.generativeai as genai
from notion_client import Client

# 1. Configurações da página (Opcional, mas deixa mais bonito)
st.set_page_config(
    page_title="Suporte CRM",
    page_icon="🤖",
    layout="centered"
)

st.title("🤖 Suporte da CRM - CDL")
st.write("Bem-vindo! Como posso ajudar você com o nosso CRM hoje?")

# 2. Puxando a chave secreta e configurando os chaves
CHAVE_API = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=CHAVE_API)
model = genai.GenerativeModel('gemini-2.5-flash')
NOTION_TOKEN = st.secrets["NOTION_TOKEN"]
notion = Client(auth=NOTION_TOKEN)
NOTION_DB_ID = st.secrets["NOTION_DATABASE_ID"]

# 3. Função para ler o Notion e criar a "Base de Conhecimento" para o bot
# O st.cache_data faz o app não ter que ler o Notion a cada mensagem (fica mais rápido)
@st.cache_data(ttl=3600)  # Cache por 1 hora
def carregar_base_conhecimento():
    base_conhecimento = ""
    try:
        def ler_conteudo_recursivo(block_id):
            texto_acumulado = ""
            # Puxa os blocos do nível atual
            blocos = notion.blocks.children.list(block_id=block_id).get("results", [])
            
            for b in blocos:
                tipo = b.get("type")
                
                # 1. TEXTO COMUM (Parágrafos, Títulos, Callouts, Listas)
                if tipo in b and "rich_text" in b[tipo]:
                    textos = b[tipo]["rich_text"]
                    if textos:
                        texto_extraido = "".join([t.get("plain_text", "") for t in textos])
                        texto_acumulado += f"\n{texto_extraido}"
                
                # 2. SUB-PÁGINA (Ex: LEAD, ORGANIZAÇÃO)
                elif tipo == "child_page":
                    titulo = b["child_page"].get("title", " SemTítulo")
                    texto_acumulado += f"\n\n### MÓDULO: {titulo.upper()}###"
                    # Encontra na página para ler o que tem dentro
                    texto_acumulado += ler_conteudo_recursivo(b["id"])
                    
                # 3. TABELA / BANCO DE DADOS
                elif tipo == "child_database":
                    titulo_db = b["child_database"].get("title", " Banco de Dados")
                    texto_acumulado += f"\n\n###--- BANCO DE DADOS: {titulo_db.upper()} --- ###"
                    try:
                        # Consulta as linhas da tabela
                        linhas = notion.databases.query(database_id=b["id"]).get("results", [])
                        for linha in linhas:
                            texto_acumulado += "\n"
                            props = linha.get("properties", {})
                            for nome_coluna, dados_coluna in props.items():
                                p_type = dados_coluna.get("type")
                                conteudo = ""
                                
                                # Extrai texto de colunas de Título ou Texto Rico
                                if p_type == "title":
                                    conteudo = "".join([t.get("plain_text", "") for t in dados_coluna["title"]])
                                elif p_type == "rich_text":
                                    conteudo = "".join([t.get("plain_text", "") for t in dados_coluna["rich_text"]])
                                elif p_type == "select" and dados_coluna["select"]:
                                    conteudo = dados_coluna["select"]["name"]
                                if conteudo:
                                    texto_acumulado += f"[{nome_coluna}: {conteudo}]"
                    except Exception as e:
                        texto_acumulado += f"\n[Erro ao ler banco de dados: {e}]"
                        
                # 4. TABELA SIMPLES
                elif tipo == "table":
                    texto_acumulado += "\n\n###--- TABELA FAQ ---###"
                    try:
                        linhas_tabela = notion.blocks.children.list(block_id=b["id"]).get("results", [])
                        for linha in linhas_tabela:
                            if linha.get("type") == "table_row":
                                celulas = linha["table_row"]["cells"]
                                # Junta o texto de cada coluna separando com " | "
                                texto_linha = " | ".join(["".join([t.get("plain_text", "") for t in celula]) for celula in celulas])
                                texto_acumulado += f"\n| {texto_linha} |"
                                
                    except Exception as e:
                        texto_acumulado += f"\n[Erro ao ler tabela: {e}]"
                                
                # 5. Blocos com filhos (Toggles/Setinhas)
                elif b.get("has_children") and tipo not in ["child_page", "child_database", "table"]:
                    texto_acumulado += ler_conteudo_recursivo(b["id"])
                    
            return texto_acumulado
        
        # Inicia a leitura a partir da sua página principal
        return ler_conteudo_recursivo(NOTION_DB_ID)
                    
    except Exception as e:
        return f"Erro ao carregar base de conhecimento: {e}"
    
#4. Carrega a base de conhecimento silenciosamente (sem mostrar o erro pro usuário, só pro dev)
conhecimento_empresa = carregar_base_conhecimento()

# 5. Debug Visual (Para garantir que ele leu os textos):
with st.expander("🛠️ Debug - Clique para ver a Base de Conhecimento lida"):
    st.write(conhecimento_empresa)

# 6. Inicializa o histórico de mensagens na memória do Streamlit
if "messages" not in st.session_state:
    st.session_state.messages = []

# 7. Exibe as mensagens que já estão no histórico na tela
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 8. Cria a caixa de texto para o usuário digitar
if prompt := st.chat_input("Digite sua dúvida aqui..."):
    
    # Aparece a mensagem do usuário na tela e salva no histórico
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # RECURSO NOVO: Criando o "Resumo" da conversa para o modelo entender o contexto (pode ser útil se a conversa ficar longa)
    historico = ""
    # Pega as últimas 6 mensagens trocadas, ignorando a que o usuário acabou de digitar
    for msg in st.session_state.messages[-7:-1]:  # Pega as últimas 6 mensagens (pode ajustar esse número)
        quem = "Usuário" if msg["role"] == "user" else "Assistente"
        historico += f"{quem}: {msg['content']}"

    # Prepara a instrução para o Gemini
    # Aqui é onde "obrigamos" ele a usar a base de conhecimento do Notion para responder
    instrucao_secreta = f"""
    VVocê é o Chen, assistente de suporte do CRM. 
    O seu objetivo é ajudar os colaboradores usando a base de conhecimento do Notion fornecida.

    INSTRUÇÕES:
    1. Utilize a base abaixo para responder. Considere sinónimos (ex: "alterar" pode ser o mesmo que "recuperar" ou "esquecer" no contexto de senhas).
    2. A base contém tabelas formatadas com barras '|'. Identifique a 'Pergunta' e use a 'Resposta' correspondente.
    3. Se o utilizador perguntar algo que não está na base, não invente. Nesse caso, envie os links de ajuda do YouTube:
       - https://www.youtube.com/playlist?list=PLzj5Yw3bh5tWOgrbjmGBPGtGC88oMYZ8l
       - https://www.youtube.com/playlist?list=PLzj5Yw3bh5tWe6I7KCn6pcLOQ1-LKwtIv

    BASE DE CONHECIMENTO:
    {conhecimento_empresa}

    HISTÓRICO:
    {historico}

    PERGUNTA DO UTILIZADOR: {prompt}
    """

    # Espaço onde a resposta do bot vai aparecer
    with st.chat_message("assistant"):
        # Uma mensagem de carregamento temporária
        placeholder = st.empty()
        placeholder.markdown("⏳ Consultando o manual do CRM...")
        
        try:
            # Envia a mensagem do usuário para o modelo e recebe a resposta
            resposta_ia = model.generate_content(instrucao_secreta)
            texto_resposta = resposta_ia.text

            # Atualiza a mensagem de carregamento com a resposta real
            placeholder.markdown(texto_resposta)
                
            # Salva a resposta do bot no histórico
            st.session_state.messages.append({"role": "assistant", "content": texto_resposta})
            
        except Exception as e:
            placeholder.markdown("❌ Ocorreu um erro ao obter a resposta. Tente novamente.")
            st.error(f"Erro: {e}")