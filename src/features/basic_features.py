import pandas as pd
import sklearn.preprocessing
import logging
import numpy as np
import sqlite3
from io import StringIO
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_historic_p(db_location,citation_date_column,grouping_columns,nsp_column,nsp_p_column_name):
    history = pd.read_sql_table("history", f'sqlite:///{db_location}').sort_values(by=citation_date_column)
    history["citations_cumcount"] = history.groupby(by=grouping_columns)[nsp_column].cumcount()
    history["nsp_cumsum"] = history.groupby(by=grouping_columns)[nsp_column].cumsum()
    history[nsp_p_column_name] = history["nsp_cumsum"] / history["citations_cumcount"]
    history[nsp_p_column_name] = np.where(history["citations_cumcount"] == 0,0.5,history[nsp_p_column_name])
    del history["citations_cumcount"]
    del history["nsp_cumsum"]
    return history
class Featurizer:
    def __init__(self,interim_dataset_location):
        self.data = pd.read_csv(interim_dataset_location)
        logger.info("current shape: {}".format(self.data.shape))
    def generate_basic_features(self,use_reserve=True, idx="PAID",db_location="data/processed/history2.sqlite"):
        self.idx = idx
        self.data["FechaCita"] = pd.to_datetime(self.data["FechaCita"])
        self.data["HoraCita"] = pd.to_datetime(self.data["HoraCita"])
        self.data["FechaNac"] = pd.to_datetime(self.data["FechaNac"])
        if use_reserve:
            self.data["FechaReserva"] = pd.to_datetime(self.data["FechaReserva"])
            self.data["delay"] = (self.data["FechaCita"]-self.data["FechaReserva"]).astype('timedelta64[W]')
        
        self.historic_p_s = get_historic_p(db_location,"FechaCita",[self.idx,"Especialidad"],"NSP","nsp_p")
        self.historic_p_g = get_historic_p(db_location,"FechaCita",[self.idx],"NSP","nsp_p_g")
        self.data = self.data.merge(self.historic_p_s,how="left")
        self.data = self.data.merge(self.historic_p_g,how="left")
        
        self.data["age"] = (self.data["FechaCita"]-self.data["FechaNac"]).astype('timedelta64[D]')/365.25
        self.data["month"] = self.data["FechaCita"].dt.month_name()
        self.data["day"] = self.data["FechaCita"].dt.day_name()
        self.data["hour"] = self.data["HoraCita"].dt.hour

        self.data = self.data[self.data["EstadoCita"].isin(["Atendido","No Atendido"])]
        self.data["NSP"] = np.where(self.data["EstadoCita"] == "No Atendido",1,0)

        
        logger.info("current shape: {}".format(self.data.shape))

        self.data = self.data[(self.data["age"] <= 15) & (self.data["age"] >= 0)]
        if use_reserve:
            self.data = self.data[(self.data["delay"] <= 10) & (self.data["delay"] >= 0)]
        self.data = self.data[(self.data["hour"] <= 17) & (self.data["hour"] >= 8)]
        self.data["hour"] = self.data["hour"].astype('category')
        if use_reserve:
            self.data["delay"] = self.data["delay"].astype('category')
        logger.info("current shape: {}".format(self.data.shape))

        self.data["age"] = pd.cut(self.data["age"],[0,0.5,5,12,18],right=False,labels=["lactante","infante_1","infante_2","adolescente"])
        self.data_to_history = self.data[[idx,"Especialidad","FechaCita"]]

        ## Crear clasificacion TipoPrestacion medica/no medica a partir de los codigos FONASA

        # Lista de codigos de consultas medicas
        CodigosConsultaMedica = ['101111','101112','101113','903001']

        # Lista de codigos de consultas no medicas
        CodigosConsultaNoMedica = ['903002','903303','102001','102005','102006','102007',
                                '1101004','1101011','1101041','1101043','1101045','1201009',
                                '1301008','1301009']

        # Lista de codigos de procedimientos
        CodigosProcedimiento = ['305048','901005','1101009','1101010','1701003',
                                '1701006','1701045','1707002','1901030','2701013',
                                '2701015','2702001','AA09A3','AA09A4','Estudio']

        self.data['TipoPrestacionC'] = 'OTRO'

        self.data.loc[self.data['CodPrestacion'].isin(CodigosConsultaMedica),'TipoPrestacionC'] = 'ConsultaMedica'
        self.data.loc[self.data['CodPrestacion'].isin(CodigosConsultaNoMedica),'TipoPrestacionC'] = 'ConsultaNoMedica'
        self.data.loc[self.data['CodPrestacion'].isin(CodigosProcedimiento),'TipoPrestacionC'] = 'Procedimiento'
        #DD.loc[np.logical_not(DD['CodPrestacion'].isin(CodigosConsultaMedica+CodigosConsultaNoMedica+CodigosProcedimiento)),'TipoPrestacionC'] = 'OTRO'

        ## Crear clasificacion Profesional Medico/No medico

        # lista de tipos de profesionales medicos
        Profesional_medico = ['Médico','Médico Cirujano','Odontólogo/Dentista',
                            'Cirujano(a) Dentista','Ginecólogo(a)','Psiquiatra']

        #map(unicode,Profesional_medico)

        # lista de tipos de profesionales no medicos
        Profesional_noMedico = ['Enfermera (o)','Psicólogo (a)',#'No Mencionada',
                                'Kinesiólogo (a)','Fonoaudiólogo (a)','Tecnólogo Médico',
                                'Nutricionista','Terapeuta Ocupacional','Asistente Social',
                                'Técnico Paramédico']

        #map(unicode,Profesional_medico)

        # crear columna TipoProfesionalC (Clasificacion)
        self.data['TipoProfesionalC'] = 'OTRO'

        # transformar las entradas de TipoProfesional unicode a string
        self.data['TipoProfesional'].apply(lambda x: str(x))

        # decir si el tipo de profesional es medico o no medico, guardar en TipoProfesionalC
        self.data.loc[self.data['TipoProfesional'].astype(str).isin(Profesional_medico),'TipoProfesionalC'] = 'Medico'
        self.data.loc[self.data['TipoProfesional'].astype(str).isin(Profesional_noMedico),'TipoProfesionalC'] = 'NoMedico'
        #DD.loc[np.logical_not(DD['TipoProfesional'].isin(Profesional_medico)),'TipoProfesionalC'] = 'NoMedico'

        #print DD.loc[DD['TipoProfesionalC']=='Medico']['TipoProfesional'].value_counts()
        #print ''
        #
        #print DD.loc[DD['TipoProfesionalC']=='NoMedico']['TipoProfesional'].value_counts()
        if use_reserve:
            self.data = self.data.drop(columns=[idx,"FechaCita","HoraCita","FechaNac","FechaReserva","EstadoCita",'TipoProfesional', 'CodPrestacion'], axis=1)
        else:
            self.data = self.data.drop(columns=[idx,"FechaCita","HoraCita","FechaNac","EstadoCita",'TipoProfesional', 'CodPrestacion'], axis=1)
        logger.info(self.data.columns)
        self.data = pd.get_dummies(self.data)
        logger.info("current shape: {}".format(self.data.shape))
        
    def write(self,data_location):
        self.data.dropna(inplace=True)
        logger.info(self.data.columns)
        self.data.to_csv(data_location,index=False)


class FeaturizerCrsco:
    def __init__(self,interim_dataset_location):
        self.data = pd.read_csv(interim_dataset_location)
        logger.info("current shape: {}".format(self.data.shape))
    def generate_basic_features(self):
        self.data["FechaCita"] = pd.to_datetime(self.data["FechaCita"])
        self.data.sort_values(by="FechaCita",ascending=True,inplace=True)
        self.data["HoraCita"] = pd.to_datetime(self.data["HoraCita"])
        self.data["FechadeNac"] = pd.to_datetime(self.data["FechadeNac"])
        self.data["age"] = (self.data["FechaCita"]-self.data["FechadeNac"]).astype('timedelta64[D]')/365.25
        self.data["month"] = self.data["FechaCita"].dt.month_name()
        self.data["day"] = self.data["FechaCita"].dt.day_name()
        self.data["hour"] = self.data["HoraCita"].dt.hour

        self.data = self.data[self.data["EstadoCita"].isin(["Atendido","No Atendido"])]
        self.data["NSP"] = np.where(self.data["EstadoCita"] == "No Atendido",1,0)

        
        logger.info("current shape: {}".format(self.data.shape))

        self.data = self.data[(self.data["hour"] <= 17) & (self.data["hour"] >= 8)]
        self.data["hour"] = self.data["hour"].astype('category')
        logger.info("current shape: {}".format(self.data.shape))

        self.data["age"] = pd.cut(self.data["age"],[0,0.5,5,12,18,26,59,100],right=False,include_lowest=True,labels=["lactante","infante_1","infante_2","adolescente","joven","adulto","adulto mayor"])
        self.data_to_history = self.data[["Rut","Especialidad","FechaCita"]]

        self.data = self.data.drop(columns=["Rut","FechaCita","HoraCita","FechadeNac","EstadoCita", 'CodigoPrestacion'], axis=1)
        logger.info(self.data.columns)
        self.data = pd.get_dummies(self.data)
        logger.info("current shape: {}".format(self.data.shape))

    def generate_history_feature(self,db_location):
        conn = sqlite3.connect(db_location)
        cur = conn.cursor()
        def get_history_from_db(Rut,Especialidad,FechaCita,span):
            cur.execute("""
            SELECT sum(NSP) as NSP_count, count(NSP) as citation_count
            FROM history
            WHERE Rut = {}
                AND Especialidad = "{}"
                AND FechaCita >= date("{}", "-{} month")
                AND FechaCita < date("{}")
            """.format(Rut,Especialidad,FechaCita,span,FechaCita)
            )
            row = cur.fetchone()
            if row[1] == 0:
                p_NSP = 0.5
            else:
                try:
                    p_NSP = row[0] / row[1]
                except TypeError:
                    p_NSP = 0.5
            logger.info("{} {} {} {} {} {}".format(Rut,Especialidad,FechaCita,row[0],row[1],p_NSP))
            return p_NSP

        def get_history_from_db_simple(df):
            history = pd.read_sql("""
            
            SELECT
                Rut,
                Especialidad,
                sum(NSP) as NSP_count,
                count(NSP) as citation_count
            FROM
                history
            GROUP BY
                Rut,
                Especialidad
            
            """,conn)
            logger.info(df.shape)
            df = df.merge(history,on=["Rut","Especialidad"],how="left")
            logger.info(df.shape)
            return df["NSP_count"] / df["citation_count"]
        
        def get_history_from_db_simple_general(df):
            history = pd.read_sql("""
            
            SELECT
                Rut,
                sum(NSP) as NSP_count,
                count(NSP) as citation_count
            FROM
                history
            GROUP BY
                Rut
            
            """,conn)
            logger.info(df.shape)
            df = df.merge(history,on=["Rut"],how="left")
            logger.info(df.shape)
            return df["NSP_count"] / df["citation_count"]

        logger.info(self.data.shape)
        self.data["p_NSP"] = get_history_from_db_simple(self.data_to_history[["Rut","Especialidad"]]).fillna(value=0.5)
        self.data["p_NSP_g"] = get_history_from_db_simple_general(self.data_to_history[["Rut"]]).fillna(value=0.5)

    def write(self,data_location):
        self.data.dropna(inplace=True)
        logger.info(self.data.columns)
        self.data.to_csv(data_location,index=False)


class FeaturizerHrt:
    def __init__(self,interim_dataset_location):
        self.data = pd.read_csv(interim_dataset_location)
        logger.info("current shape: {}".format(self.data.shape))
    def generate_basic_features(self):
        self.data["FECHA_CITA"] = pd.to_datetime(self.data["FECHA_CITA"])
        self.data.sort_values(by="FECHA_CITA",ascending=True,inplace=True)
        self.data["HORA_CITA"] = pd.to_datetime(self.data["HORA_CITA"])
        self.data["FECHANAC"] = pd.to_datetime(self.data["FECHANAC"])
        self.data["FECHA_RESERVA"] = pd.to_datetime(self.data["FECHA_RESERVA"])
        self.data["delay"] = (self.data["FECHA_CITA"]-self.data["FECHA_RESERVA"]).astype('timedelta64[W]')
        self.data["age"] = (self.data["FECHA_CITA"]-self.data["FECHANAC"]).astype('timedelta64[D]')/365.25
        self.data["month"] = self.data["FECHA_CITA"].dt.month_name()
        self.data["day"] = self.data["FECHA_CITA"].dt.day_name()
        self.data["hour"] = self.data["HORA_CITA"].dt.hour

        self.data["NSP"] = np.where(self.data["FECHA_HORA_CONFIRMACION_CITA"].isna(),1,0)

        
        logger.info("current shape: {}".format(self.data.shape))

        self.data = self.data[(self.data["hour"] <= 17) & (self.data["hour"] >= 8)]
        self.data = self.data[(self.data["delay"] <= 10) & (self.data["delay"] >= 0)]
        self.data["delay"] = self.data["delay"].astype('category')
        self.data["hour"] = self.data["hour"].astype('category')
        logger.info("current shape: {}".format(self.data.shape))

        self.data["age"] = pd.cut(self.data["age"],[0,0.5,5,12,18,26,59,100],right=False,include_lowest=True,labels=["lactante","infante_1","infante_2","adolescente","joven","adulto","adulto mayor"])
        self.data_to_history = self.data[["RUT","ESPECIALIDAD","FECHA_CITA"]]

        self.data = self.data.drop(columns=["RUT","FECHA_CITA","HORA_CITA","FECHANAC","FECHA_HORA_CONFIRMACION_CITA","FECHA_RESERVA"], axis=1)
        logger.info(self.data.columns)
        self.data = pd.get_dummies(self.data)
        logger.info("current shape: {}".format(self.data.shape))

    def generate_history_feature(self,db_location):
        conn = sqlite3.connect(db_location)
        cur = conn.cursor()
        def get_history_from_db(RUT,ESPECIALIDAD,FECHA_CITA,span):
            cur.execute("""
            SELECT sum(NSP) as NSP_count, count(NSP) as citation_count
            FROM history
            WHERE RUT = {}
                AND ESPECIALIDAD = "{}"
                AND FECHA_CITA >= date("{}", "-{} month")
                AND FECHA_CITA < date("{}")
            """.format(RUT,ESPECIALIDAD,FECHA_CITA,span,FECHA_CITA)
            )
            row = cur.fetchone()
            if row[1] == 0:
                p_NSP = 0.5
            else:
                try:
                    p_NSP = row[0] / row[1]
                except TypeError:
                    p_NSP = 0.5
            logger.info("{} {} {} {} {} {}".format(RUT,ESPECIALIDAD,FECHA_CITA,row[0],row[1],p_NSP))
            return p_NSP

        def get_history_from_db_simple(df):
            history = pd.read_sql("""
            
            SELECT
                RUT,
                ESPECIALIDAD,
                sum(NSP) as NSP_count,
                count(NSP) as citation_count
            FROM
                history
            GROUP BY
                RUT,
                ESPECIALIDAD
            
            """,conn)
            logger.info(df.shape)
            df = df.merge(history,on=["RUT","ESPECIALIDAD"],how="left")
            logger.info(df.shape)
            return df["NSP_count"] / df["citation_count"]
        def get_history_from_db_simple_general(df):
            history = pd.read_sql("""
            
            SELECT
                RUT,
                sum(NSP) as NSP_count,
                count(NSP) as citation_count
            FROM
                history
            GROUP BY
                RUT
            
            """,conn)
            logger.info(df.shape)
            df = df.merge(history,on=["RUT"],how="left")
            logger.info(df.shape)
            return df["NSP_count"] / df["citation_count"]
        logger.info(self.data.shape)
        self.data["p_NSP"] = get_history_from_db_simple(self.data_to_history[["RUT","ESPECIALIDAD"]]).fillna(value=0.5)
        self.data["p_NSP_g"] = get_history_from_db_simple_general(self.data_to_history[["RUT"]]).fillna(value=0.5)

    def write(self,data_location):
        self.data.dropna(inplace=True)
        logger.info(self.data.columns)
        self.data.to_csv(data_location,index=False)