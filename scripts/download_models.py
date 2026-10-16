from backend.nlp import encoder, linguistic_model
from backend.contradictions import model
if __name__=='__main__':
    print('Loading spaCy...');linguistic_model()
    print('Downloading CPU sentence embeddings...');encoder()
    print('Downloading CPU NLI...');model()
    print('Models ready in the Hugging Face / spaCy caches.')
