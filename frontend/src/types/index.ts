export interface Lead {
  id: string;
  companyName: string;
  email: string;
  phone: string;
  address: string;
}

export type Category = 
  | 'Real Estate'
  | 'E-Commerce'
  | 'Information Technology'
  | 'Healthcare'
  | 'Manufacturing'
  | 'Education'
  | 'Finance'
  | 'Hotels'
  | 'Construction'
  | 'Other';
