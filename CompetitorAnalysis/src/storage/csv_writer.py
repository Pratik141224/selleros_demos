import pandas as pd


class CSVWriter:

    @staticmethod
    def save(data, path):

        df = pd.DataFrame(data)

        df.to_csv(
            path,
            index=False
        )