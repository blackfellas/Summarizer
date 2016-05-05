#### summarizer-BF

Python 2.7.11, pip 8.1.1

Using pip, install the following modules: `pip install -r requirements.txt`

Install `punkt.zip`

    import nltk
    
    nltk.download('punkt')

Or if running on a cloud like Heroku, make sure to copy /nltk_data/tokenizers/punkt to the script folder, as well as `Procfile`
